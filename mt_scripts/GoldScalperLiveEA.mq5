//+------------------------------------------------------------------+
// GoldScalperLiveEA.mq5 -- paper-trading execution side.
//
// Division of labor: scripts/live_signal_generator.py does ALL the
// strategy thinking (indicators, SMC detection, Edge Score, direction)
// and writes plain mechanical numbers to a CSV signal file -- this EA
// just reads that file, opens trades, and manages them tick-by-tick
// (initial SL/TP, then an ATR-based trailing stop). It has no idea what
// a "round number" or "fair value gap" is, on purpose -- if the Python
// side's strategy logic ever changes, this file shouldn't need to.
//
// NOT LIVE-TESTED. Written and reasoned through carefully, mirrors
// goldscalper/backtest.py's trailing-stop logic exactly, but this exact
// file has not run against a live MT5 feed (this dev environment can't
// -- no market data access). Attach it to a DEMO account chart first,
// watch the Experts/Journal log closely, and confirm a few trades match
// expectations before trusting it further.
//+------------------------------------------------------------------+
#property strict
#include <Trade\Trade.mqh>

input string InpSignalFile   = "goldscalper_signal.csv";  // must match --signal-file from the Python side
input double InpRiskPct      = 0.01;                       // fraction of account equity risked per trade
input int    InpMagicNumber  = 20260729;
input int    InpMaxSignalAgeMinutes = 90;                  // ignore a signal older than this (EA was offline?)
input int    InpPollSeconds  = 5;                          // how often OnTimer re-checks the signal file/position

CTrade trade;
long   g_lastSignalId = -1;

int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   g_lastSignalId = (long)GlobalVariableGet2("gsc_last_signal_id", -1);
   EventSetTimer(InpPollSeconds);
   Print("GoldScalperLiveEA initialized. Watching: ", InpSignalFile, " last processed signal_id=", g_lastSignalId);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTick()
{
   ManageOpenPosition();
}

void OnTimer()
{
   ManageOpenPosition();
   if(!HasOpenPosition())
      CheckForNewSignal();
}

//+------------------------------------------------------------------+
// Helpers                                                            |
//+------------------------------------------------------------------+
double GlobalVariableGet2(string name, double fallback)
{
   if(GlobalVariableCheck(name))
      return GlobalVariableGet(name);
   return fallback;
}

bool HasOpenPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
// Read the signal CSV, act on the first row with signal_id >           |
// g_lastSignalId. Format (header row expected):                       |
// signal_id,generated_at,symbol,direction,sl_offset,tp_offset,         |
// trailing_activation_offset,trailing_distance_offset,edge_score       |
//+------------------------------------------------------------------+
void CheckForNewSignal()
{
   int handle = FileOpen(InpSignalFile, FILE_READ | FILE_CSV | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE, ',');
   if(handle == INVALID_HANDLE)
      return; // file may not exist yet -- not an error, just nothing to do

   // Skip the 9-column header row (signal_id,generated_at,symbol,direction,
   // sl_offset,tp_offset,trailing_activation_offset,trailing_distance_offset,edge_score)
   for(int i = 0; i < 9 && !FileIsEnding(handle); i++)
      FileReadString(handle);

   long   bestId = -1;
   string bestSymbol = "", bestDirection = "", bestGeneratedAt = "";
   double bestSl = 0, bestTp = 0, bestTrailAct = 0, bestTrailDist = 0;

   while(!FileIsEnding(handle))
   {
      long   signalId      = (long)StringToInteger(FileReadString(handle));
      string generatedAt   = FileReadString(handle);
      string symbol        = FileReadString(handle);
      string direction     = FileReadString(handle);
      double slOffset      = StringToDouble(FileReadString(handle));
      double tpOffset      = StringToDouble(FileReadString(handle));
      double trailActOffset= StringToDouble(FileReadString(handle));
      double trailDistOffset=StringToDouble(FileReadString(handle));
      FileReadString(handle); // edge_score, unused here

      if(signalId > g_lastSignalId && signalId > bestId)
      {
         bestId = signalId;
         bestSymbol = symbol;
         bestDirection = direction;
         bestGeneratedAt = generatedAt;
         bestSl = slOffset;
         bestTp = tpOffset;
         bestTrailAct = trailActOffset;
         bestTrailDist = trailDistOffset;
      }
   }
   FileClose(handle);

   if(bestId <= g_lastSignalId)
      return; // nothing new

   g_lastSignalId = bestId;
   GlobalVariableSet("gsc_last_signal_id", (double)g_lastSignalId);

   if(bestSymbol != _Symbol)
   {
      Print("Signal #", bestId, " is for ", bestSymbol, ", this chart is ", _Symbol, " -- ignoring.");
      return;
   }

   if(IsSignalStale(bestGeneratedAt))
   {
      Print("Signal #", bestId, " generated_at=", bestGeneratedAt, " is stale -- ignoring.");
      return;
   }

   OpenTradeFromSignal(bestDirection, bestSl, bestTp, bestTrailAct, bestTrailDist);
}

bool IsSignalStale(string generatedAtIso)
{
   // generatedAtIso like "2026-07-29T14:03:11.123456+00:00" -- compare
   // just the date+time portion against current UTC-ish server time.
   datetime generated = StringToTime(StringSubstr(generatedAtIso, 0, 19));
   if(generated <= 0)
      return false; // couldn't parse -- don't block on a formatting hiccup
   return (TimeCurrent() - generated) > InpMaxSignalAgeMinutes * 60;
}

//+------------------------------------------------------------------+
// Open a position sized by fixed-fractional risk, tag trailing         |
// parameters into the comment field so ManageOpenPosition can read     |
// them back without a separate state file.                            |
//+------------------------------------------------------------------+
void OpenTradeFromSignal(string direction, double slOffset, double tpOffset, double trailActOffset, double trailDistOffset)
{
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(tickSize <= 0 || tickValue <= 0)
   {
      Print("Could not read tick size/value for ", _Symbol, " -- aborting entry.");
      return;
   }

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskAmount = equity * InpRiskPct;
   double riskPerLot = (slOffset / tickSize) * tickValue;
   double lots = (riskPerLot > 0) ? riskAmount / riskPerLot : 0;

   double volMin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double volMax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double volStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lots = MathFloor(lots / volStep) * volStep;
   lots = MathMax(volMin, MathMin(volMax, lots));
   if(lots <= 0)
   {
      Print("Computed lot size <= 0 (risk too small vs min lot) -- aborting entry.");
      return;
   }

   string comment = StringFormat("GSC|act=%.5f|dist=%.5f", trailActOffset, trailDistOffset);

   bool ok;
   if(direction == "buy")
   {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      ok = trade.Buy(lots, _Symbol, ask, ask - slOffset, ask + tpOffset, comment);
   }
   else if(direction == "sell")
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      ok = trade.Sell(lots, _Symbol, bid, bid + slOffset, bid - tpOffset, comment);
   }
   else
   {
      Print("Unknown direction in signal: ", direction);
      return;
   }

   if(!ok)
      Print("Order failed: ", trade.ResultRetcodeDescription());
   else
      Print("Opened ", direction, " ", lots, " lots on ", _Symbol, " (risk $", riskAmount, ")");
}

//+------------------------------------------------------------------+
// Trailing stop management -- mirrors goldscalper/backtest.py exactly: |
// once profit reaches the activation offset, drop the fixed TP and     |
// trail the stop at a fixed distance behind the best price seen,       |
// never loosening it.                                                 |
//+------------------------------------------------------------------+
void ManageOpenPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;

      double trailAct = 0, trailDist = 0;
      if(!ParseTrailingParams(PositionGetString(POSITION_COMMENT), trailAct, trailDist))
         continue; // not one of ours (or comment got stripped by broker) -- leave it alone

      long   posType   = PositionGetInteger(POSITION_TYPE);
      double entry     = PositionGetDouble(POSITION_PRICE_OPEN);
      double curSl     = PositionGetDouble(POSITION_SL);
      double curTp     = PositionGetDouble(POSITION_TP);
      bool   isBuy     = (posType == POSITION_TYPE_BUY);

      string extremeKey = StringFormat("gsc_extreme_%I64u", ticket);
      string activeKey  = StringFormat("gsc_trailactive_%I64u", ticket);
      double extreme    = GlobalVariableGet2(extremeKey, entry);
      bool   trailingActive = GlobalVariableGet2(activeKey, 0) > 0.5;

      double price = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double profitOffset;

      if(isBuy)
      {
         extreme = MathMax(extreme, price);
         profitOffset = extreme - entry;
      }
      else
      {
         extreme = MathMin(extreme, price);
         profitOffset = entry - extreme;
      }
      GlobalVariableSet(extremeKey, extreme);

      if(!trailingActive && profitOffset >= trailAct)
      {
         trailingActive = true;
         GlobalVariableSet(activeKey, 1.0);
         curTp = 0; // drop the fixed target once trailing takes over
      }

      if(trailingActive)
      {
         double candidateSl = isBuy ? (extreme - trailDist) : (extreme + trailDist);
         double newSl = curSl;
         if(isBuy && candidateSl > curSl) newSl = candidateSl;
         if(!isBuy && (curSl == 0 || candidateSl < curSl)) newSl = candidateSl;

         if(newSl != curSl || curTp != PositionGetDouble(POSITION_TP))
         {
            if(!trade.PositionModify(ticket, newSl, curTp))
               Print("PositionModify failed for ticket ", ticket, ": ", trade.ResultRetcodeDescription());
         }
      }
   }
}

bool ParseTrailingParams(string comment, double &act, double &dist)
{
   if(StringFind(comment, "GSC|") != 0)
      return false;
   int actPos = StringFind(comment, "act=");
   int distPos = StringFind(comment, "dist=");
   if(actPos < 0 || distPos < 0)
      return false;
   act  = StringToDouble(StringSubstr(comment, actPos + 4, distPos - (actPos + 4) - 1));
   dist = StringToDouble(StringSubstr(comment, distPos + 5));
   return true;
}
