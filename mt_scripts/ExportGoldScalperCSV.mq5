// MT5 script: exports historical OHLCV to a CSV matching goldscalper/data.py's
// expected format (datetime, open, high, low, close, volume).
//
// Install: copy into <Data Folder>/MQL5/Scripts/, compile in MetaEditor (F7),
// then drag onto any chart. Output CSV lands in <Data Folder>/MQL5/Files/.
// Find your Data Folder via File > Open Data Folder in the MT5 terminal.
#property script_show_inputs
#property strict

input string           InpSymbol    = "XAUUSD";
input ENUM_TIMEFRAMES  InpTimeframe = PERIOD_H1;
input datetime         InpStartDate = D'2015.01.01 00:00';
input string           InpFileName  = "xauusd_h1.csv";

void OnStart()
{
   MqlRates rates[];
   ArraySetAsSeries(rates, false);

   int copied = CopyRates(InpSymbol, InpTimeframe, InpStartDate, TimeCurrent(), rates);
   if(copied <= 0)
   {
      Print("CopyRates failed, error: ", GetLastError(),
            " -- try Tools > History Center to download more history for this symbol/timeframe first.");
      return;
   }

   int handle = FileOpen(InpFileName, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
   {
      Print("FileOpen failed, error: ", GetLastError());
      return;
   }

   FileWrite(handle, "datetime", "open", "high", "low", "close", "volume");
   for(int i = 0; i < copied; i++)
   {
      FileWrite(
         handle,
         TimeToString(rates[i].time, TIME_DATE | TIME_MINUTES),
         DoubleToString(rates[i].open, _Digits),
         DoubleToString(rates[i].high, _Digits),
         DoubleToString(rates[i].low, _Digits),
         DoubleToString(rates[i].close, _Digits),
         (long)rates[i].tick_volume
      );
   }

   FileClose(handle);
   Print("Exported ", copied, " bars to MQL5/Files/", InpFileName);
}
