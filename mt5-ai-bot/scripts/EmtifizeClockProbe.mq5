// Read-only clock diagnostic. Writes only redacted lines to the Experts log.
#property script_show_inputs

input int Samples = 6;
input int IntervalMilliseconds = 1000;

void OnStart()
{
   if(Samples < 1 || Samples > 30 ||
      IntervalMilliseconds < 100 || IntervalMilliseconds > 5000)
      return;

   string symbols[] = {"EURUSD", "GBPUSD", "USDJPY"};
   ulong started = GetTickCount64();
   for(int sample = 0; sample < Samples && !IsStopped(); sample++)
   {
      PrintFormat("EMT_CLOCK clocks sample=%d elapsed_ms=%I64u connected=%d demo=%d algo=%d current=%I64d trade_server=%I64d gmt=%I64d local=%I64d gmt_offset=%d",
                  sample, GetTickCount64() - started,
                  (int)TerminalInfoInteger(TERMINAL_CONNECTED),
                  (int)(AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO),
                  (int)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED),
                  (long)TimeCurrent(), (long)TimeTradeServer(), (long)TimeGMT(),
                  (long)TimeLocal(), TimeGMTOffset());
      for(int i = 0; i < ArraySize(symbols); i++)
      {
         MqlTick tick = {};
         if(SymbolInfoTick(symbols[i], tick))
            PrintFormat("EMT_CLOCK tick sample=%d symbol=%s elapsed_ms=%I64u time=%I64d time_msc=%I64d",
                        sample, symbols[i], GetTickCount64() - started,
                        (long)tick.time, tick.time_msc);
         else
            PrintFormat("EMT_CLOCK missing sample=%d symbol=%s", sample, symbols[i]);
      }
      if(sample + 1 < Samples)
         Sleep(IntervalMilliseconds);
   }
}
