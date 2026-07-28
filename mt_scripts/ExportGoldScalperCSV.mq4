// MT4 script: exports historical OHLCV to a CSV matching goldscalper/data.py's
// expected format (datetime, open, high, low, close, volume).
//
// Install: copy into <Data Folder>/MQL4/Scripts/, compile in MetaEditor (F7),
// then drag onto any chart. Output CSV lands in <Data Folder>/MQL4/Files/.
// Find your Data Folder via File > Open Data Folder in the MT4 terminal.
#property strict
#property show_inputs

input string InpSymbol     = "XAUUSD";
input int    InpTimeframe  = PERIOD_H1;
input string InpFileName   = "xauusd_h1.csv";

void OnStart()
{
   int total = iBars(InpSymbol, InpTimeframe);
   if(total <= 0)
   {
      Print("No bars available for ", InpSymbol,
            " -- try Tools > History Center to download history for this symbol/timeframe first.");
      return;
   }

   int handle = FileOpen(InpFileName, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
   {
      Print("FileOpen failed, error: ", GetLastError());
      return;
   }

   FileWrite(handle, "datetime", "open", "high", "low", "close", "volume");

   for(int i = total - 1; i >= 0; i--)
   {
      datetime t = iTime(InpSymbol, InpTimeframe, i);
      double   o = iOpen(InpSymbol, InpTimeframe, i);
      double   h = iHigh(InpSymbol, InpTimeframe, i);
      double   l = iLow(InpSymbol, InpTimeframe, i);
      double   c = iClose(InpSymbol, InpTimeframe, i);
      long     v = iVolume(InpSymbol, InpTimeframe, i);

      FileWrite(
         handle,
         TimeToString(t, TIME_DATE | TIME_MINUTES),
         DoubleToString(o, Digits),
         DoubleToString(h, Digits),
         DoubleToString(l, Digits),
         DoubleToString(c, Digits),
         v
      );
   }

   FileClose(handle);
   Print("Exported ", total, " bars to MQL4/Files/", InpFileName);
}
