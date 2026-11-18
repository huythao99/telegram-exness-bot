//+------------------------------------------------------------------+
//|                                          TelegramGridCopier.mq5  |
//|                        Bridge nhận lệnh từ Python trên macOS     |
//+------------------------------------------------------------------+
#property copyright "Telegram -> Exness MT5 Bridge"
#property version   "1.30"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>

input string   InpSymbol            = "XAUUSDm";      // Mã Vàng trên Exness (VD: XAUUSDm, XAUUSD)
input ulong    InpMagicNumber       = 888999;         // Magic Number riêng của Bot
input int      InpSlippagePoints    = 50;             // Độ trượt giá tối đa (Points)
input bool     InpCancelPendingOnBE = true;           // Xóa lệnh Limit chưa khớp khi báo +40pip
input double   InpMarketTolerance   = 0.30;           // Biên độ (giá) cho phép khớp Market ngay đầu vùng

CTrade         trade;
CPositionInfo  posInfo;
COrderInfo     ordInfo;

string         COMMAND_FILE = "tg_command.txt";

// Lưu mốc giá dời SL chung cho kèo hiện tại (VD: BUY 3776-3778 -> 3778, SELL 3776-3778 -> 3776)
double         g_targetBESLPrice = 0.0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(InpSymbol);

   // Quét file lệnh mỗi 200ms (0.2 giây)
   EventSetMillisecondTimer(200);
   Print("✅ TelegramGridCopier v1.30 đã sẵn sàng cho mã: ", InpSymbol);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
}

//+------------------------------------------------------------------+
//| Timer function                                                   |
//+------------------------------------------------------------------+
void OnTimer()
{
   if(!FileIsExist(COMMAND_FILE))
      return;

   int handle = FileOpen(COMMAND_FILE, FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return;

   string line = FileReadString(handle);
   FileClose(handle);
   FileDelete(COMMAND_FILE); // Xóa ngay sau khi đọc để không lặp lệnh

   if(StringLen(line) == 0)
      return;

   Print("📩 Nhận lệnh từ Python: ", line);
   ProcessCommand(line);
}

//+------------------------------------------------------------------+
//| Xử lý chuỗi lệnh từ Python                                       |
//| 1. OPEN|SELL|0.01|10.00|10.00|3776.00|3776.00:3786.00:3766.00... |
//| 2. PARTIAL_BE|0.50|3776.00                                       |
//+------------------------------------------------------------------+
void ProcessCommand(string cmd)
{
   string parts[];
   int count = StringSplit(cmd, '|', parts);
   if(count < 2) return;

   string action = parts[0];

   if(action == "OPEN" && count >= 7)
   {
      string side      = parts[1];                    // BUY hoặc SELL
      double lot       = StringToDouble(parts[2]);    // 0.01
      double slDist    = StringToDouble(parts[3]);    // 10.0 (10 giá)
      double tpDist    = StringToDouble(parts[4]);    // 10.0 (10 giá)
      double beSLPrice = StringToDouble(parts[5]);    // BUY -> 3778.0, SELL -> 3776.0
      string gridStr   = parts[6];                    // Danh sách entry:sl:tp

      g_targetBESLPrice = beSLPrice;
      ExecuteGridOrders(side, lot, slDist, tpDist, gridStr);
   }
   else if(action == "PARTIAL_BE")
   {
      double ratio     = StringToDouble(parts[1]);    // 0.50 (50%)
      double beSLPrice = (count >= 3 && StringToDouble(parts[2]) > 0)
                         ? StringToDouble(parts[2])
                         : g_targetBESLPrice;

      ExecutePartialCloseAndBE(ratio, beSLPrice);
   }
}

//+------------------------------------------------------------------+
//| Rải 10 lệnh vào vùng giá (Mỗi lệnh có SL = 10 giá, TP = 10 giá)  |
//+------------------------------------------------------------------+
void ExecuteGridOrders(string side, double lot, double slDist, double tpDist, string gridStr)
{
   string items[];
   int n = StringSplit(gridStr, ',', items);

   int digits = (int)SymbolInfoInteger(InpSymbol, SYMBOL_DIGITS);
   double ask = SymbolInfoDouble(InpSymbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(InpSymbol, SYMBOL_BID);

   for(int i = 0; i < n; i++)
   {
      string fields[];
      if(StringSplit(items[i], ':', fields) != 3) continue;

      double entryPrice = NormalizeDouble(StringToDouble(fields[0]), digits);
      double slPrice    = NormalizeDouble(StringToDouble(fields[1]), digits);
      double tpPrice    = NormalizeDouble(StringToDouble(fields[2]), digits);
      string comment    = "TG_Grid_" + IntegerToString(i + 1);

      if(side == "SELL")
      {
         if(bid >= entryPrice - InpMarketTolerance)
         {
            double mktSL = NormalizeDouble(bid + slDist, digits);
            double mktTP = NormalizeDouble(bid - tpDist, digits);
            trade.Sell(lot, InpSymbol, 0, mktSL, mktTP, comment);
         }
         else if(entryPrice > bid)
         {
            trade.SellLimit(lot, entryPrice, InpSymbol, slPrice, tpPrice, ORDER_TIME_GTC, 0, comment);
         }
         else
         {
            trade.SellStop(lot, entryPrice, InpSymbol, slPrice, tpPrice, ORDER_TIME_GTC, 0, comment);
         }
      }
      else if(side == "BUY")
      {
         if(ask <= entryPrice + InpMarketTolerance)
         {
            double mktSL = NormalizeDouble(ask - slDist, digits);
            double mktTP = NormalizeDouble(ask + tpDist, digits);
            trade.Buy(lot, InpSymbol, 0, mktSL, mktTP, comment);
         }
         else if(entryPrice < ask)
         {
            trade.BuyLimit(lot, entryPrice, InpSymbol, slPrice, tpPrice, ORDER_TIME_GTC, 0, comment);
         }
         else
         {
            trade.BuyStop(lot, entryPrice, InpSymbol, slPrice, tpPrice, ORDER_TIME_GTC, 0, comment);
         }
      }
   }
   Print("✅ Đã rải xong ", n, " lệnh ", side, " | Mốc dời SL khi báo lãi: ", g_targetBESLPrice);
}

//+------------------------------------------------------------------+
//| Chốt 50% số lệnh + Dời SL các lệnh còn lại về mốc beSLPrice      |
//| (VD: BUY 3776-3778 -> dời SL về 3778, SELL 3776-3778 -> về 3776) |
//+------------------------------------------------------------------+
void ExecutePartialCloseAndBE(double closeRatio, double beSLPrice)
{
   // 1. Hủy các lệnh chờ (Limit/Stop) chưa khớp nếu bật cấu hình
   if(InpCancelPendingOnBE)
   {
      for(int i = OrdersTotal() - 1; i >= 0; i--)
      {
         if(ordInfo.SelectByIndex(i))
         {
            if(ordInfo.Symbol() == InpSymbol && ordInfo.Magic() == InpMagicNumber)
            {
               trade.OrderDelete(ordInfo.Ticket());
            }
         }
      }
   }

   // 2. Gom danh sách các vị thế (Positions) đang mở của Bot
   ulong tickets[];
   int totalPos = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(posInfo.SelectByIndex(i))
      {
         if(posInfo.Symbol() == InpSymbol && posInfo.Magic() == InpMagicNumber)
         {
            ArrayResize(tickets, totalPos + 1);
            tickets[totalPos] = posInfo.Ticket();
            totalPos++;
         }
      }
   }

   if(totalPos == 0)
   {
      Print("ℹ️ Không có lệnh nào đang mở để chốt 50%.");
      return;
   }

   int numToClose = (int)MathRound(totalPos * closeRatio);
   if(numToClose < 1 && totalPos >= 1) numToClose = 1;

   int digits = (int)SymbolInfoInteger(InpSymbol, SYMBOL_DIGITS);

   // 3. Đóng 50% số lệnh đầu tiên và dời SL cho 50% lệnh còn lại về beSLPrice
   for(int i = 0; i < totalPos; i++)
   {
      if(!posInfo.SelectByTicket(tickets[i])) continue;

      if(i < numToClose)
      {
         trade.PositionClose(tickets[i]);
         Print("💰 Đã đóng lệnh #", tickets[i]);
      }
      else
      {
         double targetSL  = (beSLPrice > 0.0)
                            ? NormalizeDouble(beSLPrice, digits)
                            : NormalizeDouble(posInfo.PriceOpen(), digits);
         double currentTP = NormalizeDouble(posInfo.TakeProfit(), digits);
         double currentSL = NormalizeDouble(posInfo.StopLoss(), digits);

         if(MathAbs(currentSL - targetSL) > SymbolInfoDouble(InpSymbol, SYMBOL_POINT))
         {
            if(trade.PositionModify(tickets[i], targetSL, currentTP))
               Print("🛡️ Đã dời SL về ", targetSL, " cho lệnh #", tickets[i]);
            else
               Print("⚠️ Không thể dời SL lệnh #", tickets[i], " về ", targetSL, " Error: ", GetLastError());
         }
      }
   }
}
//+------------------------------------------------------------------+
