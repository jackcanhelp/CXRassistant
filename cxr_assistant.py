import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk, ImageGrab, ImageOps, ImageEnhance, ImageFilter
import threading
import os
import math
from datetime import datetime
import google.generativeai as genai
from dotenv import load_dotenv

# CLAHE 需要 numpy + skimage；未安裝時自動降級為 PIL equalize
try:
    import numpy as np
    from skimage.exposure import equalize_adapthist
    _CLAHE_AVAILABLE = True
except ImportError:
    _CLAHE_AVAILABLE = False

# 載入 .env 檔案中的環境變數
load_dotenv()

class CXRAssistantApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CXR 判讀輔助系統 (Gemini 2.5 Pro 旗艦版)")
        self.root.geometry("1000x700")
        
        self.default_font = ("微軟正黑體", 11)
        self.current_image = None
        self.current_photo = None
        
        # 測量工具的狀態變數
        self.measure_state = 0  # 0: 閒置, 1: 正在量心臟, 2: 正在量胸廓
        self.start_x = 0
        self.start_y = 0

        self.invert_var          = tk.BooleanVar(value=False)
        self.tumor_enhance_var   = tk.BooleanVar(value=False)
        self.brightness_var = tk.IntVar(value=100)
        self.contrast_var   = tk.IntVar(value=100)
        self.sharpness_var  = tk.IntVar(value=100)
        self.edge_var       = tk.IntVar(value=0)

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
        
        # 綁定滑鼠拖曳畫線事件
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        
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

        self.btn_analyze = tk.Button(self.btn_frame, text="🔍 開始 AI 判讀 (2.5 Pro)", font=("微軟正黑體", 12, "bold"), bg="#4CAF50", fg="white", command=self.start_analysis)
        self.btn_analyze.pack(side=tk.RIGHT, padx=5)
        self.btn_analyze.config(state=tk.DISABLED)

        # 影像選項列
        self.options_frame = tk.Frame(self.right_frame)
        self.options_frame.pack(fill=tk.X, pady=(0, 6))
        tk.Checkbutton(
            self.options_frame, text="🦴 黑白反向顯示（Bone lesion 模式）",
            variable=self.invert_var, font=("微軟正黑體", 9),
            command=self._render_canvas
        ).pack(side=tk.LEFT)

        tk.Checkbutton(
            self.options_frame,
            text="🔬 腫瘤偵測增強（CLAHE + Autocontrast + Unsharp Mask）",
            variable=self.tumor_enhance_var, font=("微軟正黑體", 9),
            fg="#007700", command=self._render_canvas
        ).pack(side=tk.LEFT, padx=(12, 0))

        # ── 影像調整滑桿區 ──
        adj_frame = tk.LabelFrame(self.right_frame, text="影像調整（即時預覽，AI 判讀時同步套用）",
                                   font=("微軟正黑體", 9), fg="#333333")
        adj_frame.pack(fill=tk.X, pady=(0, 6))

        sliders = [
            ("亮度",   self.brightness_var,  50, 200),
            ("對比",   self.contrast_var,    50, 300),
            ("銳化",   self.sharpness_var,    0, 500),
            ("邊緣增強", self.edge_var,        0, 200),
        ]
        self._slider_val_labels = {}
        for col, (name, var, lo, hi) in enumerate(sliders):
            cell = tk.Frame(adj_frame)
            cell.grid(row=0, column=col, padx=6, pady=4, sticky="ew")
            adj_frame.columnconfigure(col, weight=1)

            tk.Label(cell, text=name, font=("微軟正黑體", 8)).pack(anchor="w")
            val_label = tk.Label(cell, text=str(var.get()), font=("微軟正黑體", 8), width=4, anchor="e")
            val_label.pack(side=tk.RIGHT)
            self._slider_val_labels[name] = val_label

            def make_cmd(v=var, lbl=val_label):
                def cmd(*_):
                    lbl.config(text=str(v.get()))
                    self._render_canvas()
                return cmd

            tk.Scale(cell, variable=var, from_=lo, to=hi, orient=tk.HORIZONTAL,
                     showvalue=False, length=90, command=make_cmd()
                     ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 重置按鈕
        def reset_sliders():
            self.brightness_var.set(100)
            self.contrast_var.set(100)
            self.sharpness_var.set(100)
            self.edge_var.set(0)
            for name, lbl in self._slider_val_labels.items():
                val = {"亮度": 100, "對比": 100, "銳化": 100, "邊緣增強": 0}[name]
                lbl.config(text=str(val))
            self._render_canvas()

        tk.Button(adj_frame, text="重置", font=("微軟正黑體", 8), command=reset_sliders
                  ).grid(row=1, column=3, padx=6, pady=(0, 4), sticky="e")

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

    def _clahe_enhance(self, img, clip_limit=0.03):
        """
        自適應局部直方圖均衡（CLAHE）。
        skimage 可用時使用真正的 CLAHE；否則以 PIL equalize 混合替代。
        兩者都與原圖 60/40 混合，避免過度均衡導致細節流失。
        """
        if _CLAHE_AVAILABLE:
            arr = np.array(img.convert('L')).astype(np.float64) / 255.0
            clahe_arr = equalize_adapthist(arr, clip_limit=clip_limit)
            clahe_img = Image.fromarray((clahe_arr * 255).astype(np.uint8)).convert('RGB')
        else:
            clahe_img = ImageOps.equalize(img)
        return Image.blend(img, clahe_img, alpha=0.6)

    def _apply_tumor_enhancement(self, img):
        """
        腫瘤偵測增強 pipeline（文獻實證最佳組合）：
          1. CLAHE          → 拉開心臟陰影、肺尖等暗區的密度層次
          2. Autocontrast   → 最大化整張影像動態範圍
          3. Unsharp Mask   → 突顯 2–8 cm mass 的局部密度隆起與邊緣
        手動滑桿在此 pipeline 之後疊加，讓使用者微調。
        """
        img = self._clahe_enhance(img, clip_limit=0.03)
        img = ImageOps.autocontrast(img, cutoff=0.5)
        img = img.filter(ImageFilter.UnsharpMask(radius=5, percent=150, threshold=2))
        return img

    def _get_processed_image(self):
        """套用所有滑桿與反轉設定，回傳處理後的 PIL Image（原圖不變）。"""
        if self.current_image is None:
            return None
        img = self.current_image.copy()
        if self.invert_var.get():
            img = ImageOps.invert(img)
        # 腫瘤增強 pipeline（在手動滑桿前套用）
        if self.tumor_enhance_var.get():
            img = self._apply_tumor_enhancement(img)
        img = ImageEnhance.Brightness(img).enhance(self.brightness_var.get() / 100)
        img = ImageEnhance.Contrast(img).enhance(self.contrast_var.get() / 100)
        img = ImageEnhance.Sharpness(img).enhance(self.sharpness_var.get() / 100)
        edge_val = self.edge_var.get()
        if edge_val > 0:
            img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=edge_val, threshold=2))
        return img

    def _render_canvas(self, *_):
        """將處理後影像渲染至 canvas。"""
        img_thumb = self._get_processed_image()
        if img_thumb is None:
            return
        self.canvas.update()
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if canvas_width < 10:
            canvas_width, canvas_height = 430, 500

        img_thumb.thumbnail((canvas_width, canvas_height), Image.Resampling.LANCZOS)
        self.current_photo = ImageTk.PhotoImage(img_thumb)
        self.canvas.delete("cxr_image")
        self.canvas.create_image(canvas_width // 2, canvas_height // 2,
                                  image=self.current_photo, anchor=tk.CENTER,
                                  tags="cxr_image")
        self.canvas.tag_lower("cxr_image")

    def display_image(self, img):
        self.current_image = img.copy()
        # 載入新圖：重置所有調整
        self.invert_var.set(False)
        self.tumor_enhance_var.set(False)
        self.brightness_var.set(100)
        self.contrast_var.set(100)
        self.sharpness_var.set(100)
        self.edge_var.set(0)
        for name, lbl in self._slider_val_labels.items():
            lbl.config(text=str({"亮度": 100, "對比": 100, "銳化": 100, "邊緣增強": 0}[name]))

        self.canvas.delete("all")
        self._render_canvas()

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
        self.canvas.delete("measure") 
        
        messagebox.showinfo("CT Ratio 測量 (步驟 1/2)", 
                            "請測量【心臟寬度】：\n\n"
                            "在心臟最左緣「按住」滑鼠左鍵，向右拖曳至心臟最右緣後「放開」。")

    def on_canvas_press(self, event):
        if self.measure_state == 0:
            return

        self.start_x, self.start_y = event.x, event.y
        color = "orange" if self.measure_state == 1 else "#00FF00" 
        
        r = 3
        self.canvas.create_oval(self.start_x-r, self.start_y-r, self.start_x+r, self.start_y+r, 
                                fill=color, outline=color, tags="measure_temp")

    def on_canvas_drag(self, event):
        if self.measure_state == 0:
            return
            
        color = "orange" if self.measure_state == 1 else "#00FF00"
        self.canvas.delete("measure_preview")
        self.canvas.create_line(self.start_x, self.start_y, event.x, event.y, 
                                fill=color, width=2, dash=(5, 5), tags="measure_preview")

    def on_canvas_release(self, event):
        if self.measure_state == 0:
            return

        end_x, end_y = event.x, event.y
        dist = math.hypot(end_x - self.start_x, end_y - self.start_y)
        self.canvas.delete("measure_temp", "measure_preview")
        
        if dist < 5:
            return

        color = "orange" if self.measure_state == 1 else "#00FF00"
        r = 3
        
        self.canvas.create_oval(self.start_x-r, self.start_y-r, self.start_x+r, self.start_y+r, fill=color, outline=color, tags="measure")
        self.canvas.create_line(self.start_x, self.start_y, end_x, end_y, fill=color, width=2, dash=(5, 5), tags="measure")
        self.canvas.create_oval(end_x-r, end_y-r, end_x+r, end_y+r, fill=color, outline=color, tags="measure")

        if self.measure_state == 1:
            self.heart_width = dist
            self.measure_state = 2
            messagebox.showinfo("CT Ratio 測量 (步驟 2/2)", 
                                "心臟寬度已記錄。\n\n"
                                "請繼續測量【胸廓寬度】：\n"
                                "在胸廓左側內緣「按住」滑鼠左鍵，向右拖曳至右側內緣後「放開」。")

        elif self.measure_state == 2:
            self.thorax_width = dist
            ct_ratio = self.heart_width / self.thorax_width
            self.measure_state = 0
            
            result_msg = f"測量完成！\n\nCardiothoracic (CT) Ratio = {ct_ratio:.3f}"
            if ct_ratio > 0.5:
                result_msg += "\n\n⚠️ 結果大於 0.5，提示可能有心室肥大 (Cardiomegaly) 跡象。"
            else:
                result_msg += "\n\n✅ 結果小於 0.5，心臟大小在正常範圍內。"
            
            messagebox.showinfo("測量結果", result_msg)
            self.report_text.insert(tk.END, f"\n[手動測量結果] CT Ratio: {ct_ratio:.3f}\n")
            self.btn_export.config(state=tk.NORMAL)

    # --- AI 判讀邏輯 ---
    def start_analysis(self):
        if self.current_image is None:
            return
            
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            messagebox.showerror("錯誤", "找不到 API Key！\n請確定程式同目錄下有 .env 檔案。")
            return

        self.btn_analyze.config(state=tk.DISABLED, text="⏳ AI 判讀中...")
        self.btn_export.config(state=tk.DISABLED)
        self.report_text.delete(1.0, tk.END)
        self.report_text.insert(tk.END, "正在使用 Gemini 2.5 進行高精度病灶掃描...\n請稍候...")

        img_to_send = self._get_processed_image()  # 在主執行緒取得處理後影像
        threading.Thread(target=self._real_ai_analysis_process, args=(api_key, img_to_send), daemon=True).start()

    def _real_ai_analysis_process(self, api_key, img_to_send):
        try:
            genai.configure(api_key=api_key)
            
            # 【升級】使用最新的 gemini-2.5-pro 作為首選旗艦模型
            models_to_try = [
                'gemini-2.5-pro',
                'gemini-2.5-flash'
            ]
            
            # 專攻腫瘤與微小病灶的 Prompt
            prompt = """
            你現在是一位大型醫學中心的「胸腔腫瘤專科」資深放射科主治醫師 (Attending Thoracic Radiologist)。
            請根據提供的胸部 X 光片 (CXR)，撰寫一份極度精簡、專業的影像判讀報告。

            【強制檢索指令 (Search Pattern)】：
            在輸出報告前，請務必先仔細檢視以下容易隱藏肺癌 (Lung Cancer/Nodule/Mass) 的高風險盲區：
            1. 肺尖 (Apices) 與鎖骨交疊處
            2. 肺門區 (Hilar regions) 是否不對稱或增厚
            3. 心臟後方 (Retrocardiac area)
            4. 橫膈膜下方與肋膈角
            5. 骨骼是否有侵蝕 (Bone destruction)
            仔細尋找任何邊界不清、有毛刺感 (Spiculated)、或異常的高密度陰影。

            【定向校準（必須在分析前先執行）】：
            在描述任何病灶位置之前，先完成以下定向步驟：
            - 找出心臟主體（cardiac bulk / heart shadow）位於影像的哪一側
            - 心臟主體所在的那一側 = 病患的「左側（Left）」
            - 相對的另一側 = 病患的「右側（Right）」
            - 所有病灶的 Left / Right 均以此視覺錨點為基準，以病患解剖方向報告
            注意：請勿依賴影像的絕對左右來判斷，只以心臟位置為唯一定向依據。

            【嚴格寫作規範】：
            1. 語氣：電報式 (Telegraphic style)，簡明扼要。
            2. 正常部位：若構造正常，只需寫 "Unremarkable"，不解釋原因。
            3. 若發現疑似病灶，請具體描述其「位置 (如 RUL, LLL)」、「大小估計」、「邊界特徵 (如 well-defined, ill-defined)」。
            4. 語言：以醫學英文為主，輔以繁體中文說明。

            請嚴格輸出以下格式：

            [TECHNIQUE]
            (若無特殊狀況填 Routine)

            [FINDINGS]
            - Lungs & Pleura: (精簡描述異常，若無病灶填 Unremarkable)
            - Heart & Mediastinum: (精簡描述，若正常填 Unremarkable)
            - Bones & Soft Tissues: (精簡描述，若正常填 Unremarkable)

            [IMPRESSION]
            1. (最可能的診斷，若有疑似腫瘤請列為第一點並強烈建議 Chest CT)
            2. (鑑別診斷 2，若無則免)
            """
            
            report_content = None
            successful_model = ""
            last_error = ""

            # 嘗試 2.5 系列模型
            for model_name in models_to_try:
                try:
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content([prompt, img_to_send])
                    report_content = response.text
                    successful_model = model_name
                    break 
                except Exception as e:
                    last_error = str(e)
                    continue
            
            if report_content is None:
                report_content = f"❌ AI 判讀發生致命錯誤，2.5 系列模型無法存取：\n\n{last_error}\n\n(請確認 API Key 權限與連線)"
            elif successful_model != 'gemini-2.5-pro':
                report_content = f"⚠️ [系統提示] 無法呼叫 Pro，已使用高速版 {successful_model} 完成判讀。\n\n" + report_content
            
        except Exception as e:
            report_content = f"❌ 系統發生預期外錯誤：\n\n{str(e)}"

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
        if "❌" not in report_content:
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