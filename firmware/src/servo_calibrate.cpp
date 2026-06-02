// #include <Arduino.h>

// const int SERVO_PIN = 5; 
// const int PWM_FREQ = 50;     
// const int PWM_RES = 14;      
// const int NUM_RUNS = 5;      // Số lần chạy thử để lấy trung bình

// uint32_t usToDuty(int us) {
//     return (uint32_t)((us * 16384) / 20000);
// }

// void setup() {
//     Serial.begin(115200);
//     delay(2000);
//     ledcAttach(SERVO_PIN, PWM_FREQ, PWM_RES);
    
//     Serial.println("\n=======================================================");
//     Serial.println("   HỆ THỐNG CALIBRATE ĐA LƯỢT CHỐNG SAI SỐ PHẢN XẠ");
//     Serial.println("=======================================================");
    
//     int leftResults[NUM_RUNS];
//     int rightResults[NUM_RUNS];

//     for (int run = 0; run < NUM_RUNS; run++) {
//         Serial.printf("\n>>> --- HIỆP %d / %d ---\n", run + 1, NUM_RUNS);
        
//         // Xóa sạch bộ đệm Serial đề phòng bạn ấn nhầm từ hiệp trước
//         while(Serial.available() > 0) { Serial.read(); }

//         // --- DÒ BIÊN TRÁI ---
//         Serial.println("[TRÁI] Đang quét... Nhìn lốp và ấn ENTER ngay khi chạm khung!");
//         delay(1500); // Chờ 1.5s để người chuẩn bị sẵn sàng ngón tay
        
//         int currentLeft = 1000; 
//         for (int us = 1500; us >= 1000; us -= 5) {
//             ledcWrite(SERVO_PIN, usToDuty(us));
//             delay(50); // Tăng tốc độ quét (50ms) để làm 5 lần không bị quá lâu
            
//             if (Serial.available() > 0) {
//                 currentLeft = us;
//                 while(Serial.available() > 0) { Serial.read(); } // Xóa phím vừa nhấn
//                 break;
//             }
//         }
//         leftResults[run] = currentLeft;
//         Serial.printf("=> Đã ghi nhận Hiệp %d (Trái): %d us\n", run + 1, currentLeft);
        
//         // Trả về thẳng lái nghỉ ngơi giữa hiệp
//         ledcWrite(SERVO_PIN, usToDuty(1500));
//         delay(1000);

//         // --- DÒ BIÊN PHẢI ---
//         Serial.println("[PHẢI] Đang quét... Nhìn lốp và ấn ENTER ngay khi chạm khung!");
//         delay(1500);
        
//         int currentRight = 2000;
//         for (int us = 1500; us <= 2000; us += 5) {
//             ledcWrite(SERVO_PIN, usToDuty(us));
//             delay(50);
            
//             if (Serial.available() > 0) {
//                 currentRight = us;
//                 while(Serial.available() > 0) { Serial.read(); }
//                 break;
//             }
//         }
//         rightResults[run] = currentRight;
//         Serial.printf("=> Đã ghi nhận Hiệp %d (Phải): %d us\n", run + 1, currentRight);
        
//         ledcWrite(SERVO_PIN, usToDuty(1500));
//         delay(1000);
//     }

//     // --- XỬ LÝ THỐNG KÊ TOÁN HỌC ---
//     float sumLeft = 0;
//     float sumRight = 0;
//     for (int i = 0; i < NUM_RUNS; i++) {
//         sumLeft += leftResults[i];
//         sumRight += rightResults[i];
//     }
    
//     // Tính trung bình cộng và cộng/trừ 10us biên an toàn (Safety Padding)
//     int avgLeft = (int)(sumLeft / NUM_RUNS) + 10;  
//     int avgRight = (int)(sumRight / NUM_RUNS) - 10; 

//     // BÁO CÁO KẾT QUẢ ĐẸP ĐẼ CHO KỸ SƯ
//     Serial.println("\n=======================================================");
//     Serial.println("             BẢNG TỔNG HỢP DỮ LIỆU THỰC NGHIỆM         ");
//     Serial.println("=======================================================");
//     Serial.println("  Hiệp Số  |   Max Left (us)   |   Max Right (us)  ");
//     Serial.println("-------------------------------------------------------");
//     for (int i = 0; i < NUM_RUNS; i++) {
//         Serial.printf("     %d     |      %d us      |      %d us\n", i + 1, leftResults[i], rightResults[i]);
//     }
//     Serial.println("-------------------------------------------------------");
//     Serial.println("[PHÂN TÍCH] Đang tính toán trung bình và áp dụng biên an toàn (+10us/-10us)...");
//     Serial.printf("👉 KẾT LUẬN GÓC KHÓA CUỐI CÙNG: [%d us <--> %d us]\n", avgLeft, avgRight);
//     Serial.println("=======================================================");
// }

// void loop() {
//     // Để trống vì chỉ cần chạy setup 1 lần duy nhất
// }