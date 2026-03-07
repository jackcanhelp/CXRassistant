import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk, ImageGrab
import threading
import os
import math
from datetime import datetime
import google.generativeai as genai
from dotenv import load_dotenv

# 載入 .env 檔案中的環境變數
load_dotenv()

class CXRAssistantApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CXR X光判讀輔助系統 (動態測量版)")
        self.root.geometry("1000x700")
        
        self.default_font = ("微軟正黑體", 11)
        self.current_image = None
        self.current_photo = None
        
        # 測量工具的狀態變數
        self.measure_state = 0  # 0: 閒置, 1: 正在量心臟, 2: 正在量胸廓
        self.measure_pts = []   # 儲存點擊的座標

        self.setup_ui()

    def setup_ui(self):
        # 左側面板：影像顯示區
        self.left_frame = tk.Frame(self.root, width=450, bg="#2c2c2c", relief=tk.SUNKEN, bd=2)
        self.left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 右側面板：控制與報告區
        self.right_frame = tk.Frame(self.root, width=500)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- 左側元件 (Canvas) ---
        self.canvas = tk.Canvas(self.left_frame, bg="#1e1e1e", cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # 綁定滑鼠事件
        self.canvas.bind("<Button-1>", self.on_canvas_click) # 左鍵點擊
        self.canvas.bind("<Motion>", self.on_canvas_motion)  # 滑鼠移動 (用來畫動態虛線)
        
        # 初始提示文字
        self.init_text_id = self.canvas.create_text(
            225, 250, text="請載入 CXR 影像\n或使用 (Win+Shift+S) 截圖後「從剪貼簿貼上」", 
            fill="white", font=self.default_font, justify=tk.CENTER
        )

        # --- 右側元件 ---
        # 圖片載入與測量按鈕區
        self.btn_frame = tk.Frame(self.right_frame)
        self.btn_frame.pack(fill=tk.X, pady=(0, 10))

        self.btn_load = tk.Button(self.btn_frame, text="📁 載入檔案", font=self.default_font, command=self.load_image_from_file)
        self.btn_load.pack(side=tk.LEFT, padx=5)

        self.btn_paste = tk.Button(self.btn_frame, text="📋 貼上截圖", font=self.default_font, command=self.load_image_from_clipboard)
        self.btn_paste.pack(side=tk.LEFT, padx=5)
        
        # 測量按鈕
        self.btn_measure = tk.Button(self.btn_frame, text="📏 測量 CT Ratio", font=self.default_font, command=self.start_ct_measurement)
        self.btn_measure.pack(side=tk.LEFT, padx=5)
        self.btn_measure.config(state=tk.DISABLED)

        self.btn_analyze = tk.Button(self.btn_frame, text="🔍 開始 AI 判讀", font=("微軟正黑體", 12, "bold"), bg="#4CAF50", fg="white", command=self.start_analysis)
        self.btn_analyze.pack(side=tk.RIGHT, padx=5)
        self.btn_analyze.config(state=tk.DISABLED)

        # 報告顯示與匯出區
        self.report_header_frame = tk.Frame(self.right_frame)
        self.report_header_frame.pack(fill=tk.X, pady=(5, 0))
        tk.Label(self.report_header_frame, text="AI 判讀報告：", font=("微軟正黑體", 12, "bold")).pack(side=tk.LEFT)
        
        self.btn_export = tk.Button(self.report_header_frame, text="💾 匯出報告", font=("微軟正黑體", 10), command=self.export_report)
        self.btn_export.pack(side=tk.RIGHT)
        self.btn_export.config(state=tk.DISABLED)

        self.report_text = scrolledtext.ScrolledText(self.right_frame, font=self.default_font, wrap=tk.WORD, height=20)
        self.report_text.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 免責聲明
        disclaimer = "⚠️ 本系統為技術展示。測量與判讀結果不可作為臨床診斷依據。"
        tk.Label(self.right_frame, text=disclaimer, font=("微軟正黑體", 9), fg="red", justify=tk.LEFT).pack(anchor=tk.W, pady=5)

    def load_image_from_file(self):
        file_path = filedialog.askopenfilename(title="選擇 CXR 圖片", filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.bmp")])
        if file_path:
            try:
                img = Image.open(file_path)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                self.display_image(img)
            except Exception as e:
                messagebox.showerror("錯誤", f"無法載入圖片:\n{str(e)}")

    def load_image_from_clipboard(self):
        try:
            img = ImageGrab.grabclipboard()
            if isinstance(img, Image.Image):
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                self.display_image(img)
            else:
                messagebox.showwarning("提示", "剪貼簿中沒有圖片！\n請先使用 Win+Shift+S 截圖。")
        except Exception as e:
            messagebox.showerror("錯誤", f"無法從剪貼簿讀取:\n{str(e)}")

    def display_image(self, img):
        self.current_image = img.copy()
        
        self.canvas.update()
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        if canvas_width < 10: 
            canvas_width, canvas_height = 430, 500

        img_thumb = img.copy()
        img_thumb.thumbnail((canvas_width, canvas_height), Image.Resampling.LANCZOS)
        
        self.current_photo = ImageTk.PhotoImage(img_thumb)
        
        self.canvas.delete("all")
        self.canvas.create_image(canvas_width//2, canvas_height//2, image=self.current_photo, anchor=tk.CENTER)
        
        self.btn_analyze.config(state=tk.NORMAL)
        self.btn_measure.config(state=tk.NORMAL)
        self.btn_export.config(state=tk.DISABLED)
        self.report_text.delete(1.0, tk.END)
        self.report_text.insert(tk.END, "✅ 影像載入成功。\n您可以點擊上方按鈕進行 AI 判讀，或手動測量 CT Ratio。\n")
        
        self.measure_state = 0

    # --- CT Ratio 測量邏輯 ---
    def start_ct_measurement(self):
        if self.current_image is None:
            return
        
        self.measure_state = 1
        self.measure_pts = []
        self.canvas.delete("measure") # 清除舊的測量線與標記
        self.canvas.delete("temp_line") # 清除動態虛線
        
        messagebox.showinfo("CT Ratio 測量 (步驟 1/2)", 
                            "請在左側 X 光片上，點擊心臟的「最左緣」。\n"
                            "點擊後移動滑鼠，會拉出一條橘色虛線，接著點擊心臟「最右緣」。")

    def on_canvas_motion(self, event):
        """處理滑鼠移動，負責畫出動態虛線"""
        if self.measure_state == 0:
            return

        # 每次移動前先清除上一條暫存的虛線
        self.canvas.delete("temp_line")

        # 狀態1且已經點了第1點：正在拉心臟測量線 (橘色虛線)
        if self.measure_state == 1 and len(self.measure_pts) == 1:
            p1 = self.measure_pts[0]
            self.canvas.create_line(p1[0], p1[1], event.x, event.y, 
                                    fill="orange", width=2, dash=(5, 5), tags="temp_line")

        # 狀態2且已經點了第3點：正在拉胸廓測量線 (綠色虛線)
        elif self.measure_state == 2 and len(self.measure_pts) == 3:
            p3 = self.measure_pts[2]
            # 這裡用亮綠色 (#32CD32 或 #00FF00) 在 X 光黑白底圖上對比度最好
            self.canvas.create_line(p3[0], p3[1], event.x, event.y, 
                                    fill="#00FF00", width=2, dash=(5, 5), tags="temp_line")

    def on_canvas_click(self, event):
        if self.measure_state == 0:
            return

        x, y = event.x, event.y
        self.measure_pts.append((x, y))
        
        # 畫個小圓點提示使用者點擊的精確位置
        r = 3
        color = "orange" if self.measure_state == 1 else "#00FF00"
        self.canvas.create_oval(x-r, y-r, x+r, y+r, fill=color, outline=color, tags="measure")

        # 已經點了兩點 (心臟寬度完成)
        if self.measure_state == 1 and len(self.measure_pts) == 2:
            self.canvas.delete("temp_line") # 刪除動態虛線
            p1, p2 = self.measure_pts[0], self.measure_pts[1]
            # 畫心臟橘色實線
            self.canvas.create_line(p1[0], p1[1], p2[0], p2[1], fill="orange", width=2, tags="measure")
            self.heart_width = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
            
            self.measure_state = 2
            messagebox.showinfo("CT Ratio 測量 (步驟 2/2)", 
                                "心臟寬度已記錄。\n\n"
                                "請接著點擊胸廓的「最左側內緣」。\n"
                                "點擊後移動滑鼠拉出綠色虛線，再點擊「最右側內緣」。")

        # 已經點了四點 (胸廓寬度完成)
        elif self.measure_state == 2 and len(self.measure_pts) == 4:
            self.canvas.delete("temp_line") # 刪除動態虛線
            p3, p4 = self.measure_pts[2], self.measure_pts[3]
            # 畫胸廓綠色實線
            self.canvas.create_line(p3[0], p3[1], p4[0], p4[1], fill="#00FF00", width=2, tags="measure")
            self.thorax_width = math.hypot(p4[0]-p3[0], p4[1]-p3[1])
            
            # 計算比例
            ct_ratio = self.heart_width / self.thorax_width
            self.measure_state = 0 # 結束測量模式
            
            # 顯示結果
            result_msg = f"測量完成！\n\nCardiothoracic (CT) Ratio = {ct_ratio:.3f}"
            if ct_ratio > 0.5:
                result_msg += "\n\n⚠️ 結果大於 0.5，提示可能有心室肥大 (Cardiomegaly) 跡象。"
            else:
                result_msg += "\n\n✅ 結果小於 0.5，心臟大小在正常範圍內。"
            
            messagebox.showinfo("測量結果", result_msg)
            
            # 將結果附加到報告區
            self.report_text.insert(tk.END, f"\n[手動測量結果] CT Ratio: {ct_ratio:.3f}\n")
            self.btn_export.config(state=tk.NORMAL)

    # --- AI 判讀邏輯 ---
    def start_analysis(self):
        if self.current_image is None:
            return
            
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            messagebox.showerror("錯誤", "找不到 API Key！\n請確定程式同目錄下有 .env 檔案，且內容包含 GEMINI_API_KEY=你的金鑰。")
            return

        self.btn_analyze.config(state=tk.DISABLED, text="⏳ AI 判讀中...")
        self.btn_export.config(state=tk.DISABLED)
        self.report_text.delete(1.0, tk.END)
        self.report_text.insert(tk.END, "正在呼叫 Gemini 視覺模型分析影像...\n請稍候...")
        
        threading.Thread(target=self._real_ai_analysis_process, args=(api_key,), daemon=True).start()

    def _real_ai_analysis_process(self, api_key):
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            prompt = """
            你現在是一位大型醫學中心的資深放射科主治醫師 (Attending Radiologist)。
            請根據提供的胸部 X 光片 (CXR)，撰寫一份極度精簡、專業且符合臨床常態的影像判讀報告。

            【嚴格寫作規範】：
            1. 語氣：電報式 (Telegraphic style)，簡明扼要，絕不講廢話。
            2. 正常部位：若構造正常，只需寫 "Unremarkable" 或 "Normal"，不要解釋原因。
            3. 客觀與主觀分離：
               - [FINDINGS] 區塊：只能客觀描述異常影像特徵（位置、形狀、密度）。
               - [IMPRESSION] 區塊：給出最可能的 1~3 個臨床診斷。
            4. 語言：以醫學英文為主，輔以繁體中文說明（台灣醫院常見的報告格式）。

            請嚴格輸出以下格式：

            [TECHNIQUE]
            (若無特殊狀況填 Routine)

            [FINDINGS]
            - Lungs & Pleura: (精簡描述異常，正常填 Unremarkable)
            - Heart & Mediastinum: (精簡描述異常，正常填 Unremarkable)
            - Bones & Soft Tissues: (精簡描述異常，正常填 Unremarkable)

            [IMPRESSION]
            1. (最可能的診斷 1)
            2. (鑑別診斷 2，若無則免)
            """
            
            response = model.generate_content([prompt, self.current_image])
            report_content = response.text
            
        except Exception as e:
            report_content = f"❌ AI 判讀發生錯誤：\n\n{str(e)}\n\n(請檢查網路連線或 API Key)"

        self.root.after(0, self._update_report_ui, report_content)

    def _update_report_ui(self, report_content):
        current_text = self.report_text.get(1.0, tk.END).strip()
        self.report_text.delete(1.0, tk.END)
        self.report_text.insert(tk.END, report_content + "\n\n")
        
        if "[手動測量結果]" in current_text:
            measure_lines = [line for line in current_text.split('\n') if "[手動測量結果]" in line]
            for m in measure_lines:
                self.report_text.insert(tk.END, m + "\n")

        self.btn_analyze.config(state=tk.NORMAL, text="🔍 重新判讀")
        if "❌ AI 判讀發生錯誤" not in report_content:
            self.btn_export.config(state=tk.NORMAL)

    def export_report(self):
        report_text = self.report_text.get(1.0, tk.END).strip()
        if not report_text:
            return
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"CXR_Report_{timestamp}.txt"
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=default_filename,
            title="儲存報告",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("=== AI CXR 輔助判讀報告 ===\n")
                    f.write(f"產出時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write(report_text)
                    f.write("\n\n==========================\n")
                    f.write("本報告由 AI 生成與輔助測量，僅供參考，不具醫療診斷效力。")
                messagebox.showinfo("成功", "報告已成功匯出！")
            except Exception as e:
                messagebox.showerror("錯誤", f"無法儲存檔案:\n{str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = CXRAssistantApp(root)
    root.mainloop()