// Read-only native MT5 timestamp probe. Never imports or calls trade APIs.
#property script_show_inputs
#property strict

input int Samples = 20;
input int IntervalMs = 250;

string Escape(const string value)
  {
   string result=value;
   StringReplace(result,"\\","\\\\");
   StringReplace(result,"\"","\\\"");
   return result;
  }

void OnStart()
  {
   const string symbols[]={"EURUSD","GBPUSD","USDJPY"};
   int handle=FileOpen("EmtifizeMt5TimeProbe.jsonl",FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle==INVALID_HANDLE)
     {
      PrintFormat("EMTIFIZE_TIME_PROBE_OPEN_ERROR=%d",GetLastError());
      return;
     }
   for(int sample=0; sample<Samples && !IsStopped(); sample++)
     {
      for(int index=0; index<ArraySize(symbols); index++)
        {
         const string symbol=symbols[index];
         SymbolSelect(symbol,true);
         MqlTick tick={};
         const bool available=SymbolInfoTick(symbol,tick);
         const long symbol_msc=(long)SymbolInfoInteger(symbol,SYMBOL_TIME_MSC);
         const long monotonic=(long)GetTickCount64();
         const datetime current=TimeCurrent();
         const datetime trade_server=TimeTradeServer();
         const datetime gmt=TimeGMT();
         const datetime local=TimeLocal();
         const string line=StringFormat(
            "{\"schema\":\"emtifize-mt5-native-time-v1\",\"sample\":%d,\"symbol\":\"%s\",\"available\":%s,\"tick_time\":%I64d,\"tick_time_msc\":%I64d,\"symbol_time_msc\":%I64d,\"time_current\":%I64d,\"time_trade_server\":%I64d,\"time_gmt\":%I64d,\"time_local\":%I64d,\"host_monotonic_ms\":%I64d,\"bid\":%.10f,\"ask\":%.10f,\"terminal_build\":%d}",
            sample,Escape(symbol),available?"true":"false",(long)tick.time,tick.time_msc,
            symbol_msc,(long)current,(long)trade_server,(long)gmt,(long)local,monotonic,
            tick.bid,tick.ask,(int)TerminalInfoInteger(TERMINAL_BUILD));
         FileWriteString(handle,line+"\r\n");
         FileFlush(handle);
        }
      Sleep(IntervalMs);
     }
   FileClose(handle);
   Print("EMTIFIZE_TIME_PROBE_COMPLETE");
  }
