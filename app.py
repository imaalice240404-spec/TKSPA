# -*- coding: utf-8 -*-
import os, json, random, time, datetime, io, base64
import streamlit as st
import pandas as pd
import google.generativeai as genai
from supabase import create_client, Client

# ==========================================
# ⚙️ 1. 系統初始化與環境設定
# ==========================================
st.set_page_config(page_title="研發部專屬 - 專利戰略分析系統", page_icon="⚡", layout="wide")

def get_config(keys):
    for k in keys:
        try: return st.secrets[k]
        except: continue
    return None

S_URL = get_config(["SUPABASE_URL"])
S_KEY = get_config(["SUPABASE_KEY"])
ADMIN_ID = "3676" # 🌟 指定後台管理員員工編號

key_pool = []
if get_config(["GOOGLE_API_KEY_1"]): key_pool.append(st.secrets["GOOGLE_API_KEY_1"])
if get_config(["GOOGLE_API_KEY_2"]): key_pool.append(st.secrets["GOOGLE_API_KEY_2"])
if not key_pool and get_config(["GOOGLE_API_KEY"]): key_pool.append(st.secrets["GOOGLE_API_KEY"])

if not all([S_URL, S_KEY, key_pool]):
    st.error("❌ 系統偵測到雲端 Secrets 設定缺失！請檢查 Streamlit 後台設定。")
    st.stop()

SELECTED_G_KEY = random.choice(key_pool)
genai.configure(api_key=SELECTED_G_KEY)
model = genai.GenerativeModel('gemini-2.5-flash', generation_config=genai.types.GenerationConfig(temperature=0.1, top_p=0.8))

@st.cache_resource
def init_supabase() -> Client:
    return create_client(S_URL, S_KEY)
supabase = init_supabase()

# ==========================================
# 🔐 2. 員工職號登入機制
# ==========================================
if 'current_user' not in st.session_state: 
    st.session_state.current_user = None

if not st.session_state.current_user:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><br><h1 style='text-align: center; color: #1e3a8a;'>⚡ 研發部專利分析系統</h1>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("### 🔐 內部人員登入")
            job_id_input = st.text_input("請輸入您的員工編號：", placeholder="例如：3676")
            if st.button("登入系統", use_container_width=True, type="primary"):
                if job_id_input.strip():
                    st.session_state.current_user = job_id_input.strip()
                    st.rerun()
                else: 
                    st.error("請輸入有效的員工編號！")
    st.stop()

IS_ADMIN = (st.session_state.current_user == ADMIN_ID)

# ==========================================
# 🧠 3. 高階專利 Prompt 庫 (嚴格還原，一字不改)
# ==========================================
DETAILED_11_RULES = """
【一、 🚦 FTO 風險判定】
(🔴 紅燈：具威脅 / 🟡 黃燈：需注意 / 🟢 綠燈：已失效。判定原則：若狀態為「公告/核准」或「公開」，絕對不可判定為綠燈！若為「消滅/無效/撤回」才可判為🟢)

【二、📸 技術核心快照】
1. 發明目的：(說明解決傳統弊病) 
2. 核心技術：(說明具體零件結構設計、材料配方或製程步驟) 
3. 宣稱功效：(說明提升了什麼物理效果，如耐壓、高頻特性、降低 ESR 等)

【三、🏢 研發部門精準派發】
[填入建議部門]。 (分發理由)

【四、🛑 先前技術與妥協分析 (防禦地雷)】
本案欲解決之舊設計缺點：(習用技術缺點)
空間配置/製程限制（破口分析）：(列出獨立項限縮最嚴格之特徵或配方參數)

【五、🧩 獨立項全要件拆解 (Claim Chart)】
最廣獨立項（請求項1）拆解：(以 1. 2. 3. 逐行條列拆解)
破口：(精準點出最容易被迴避的限制條件或製程參數)

【六、🪤 附屬項隱藏地雷探測】
(條列出具備具體結構形狀、位置、材料成分比例或參數限制的附屬項)

【七、👁️ 侵權可偵測性評估】
(極易偵測 / 需破壞性拆解如切片(Cross-section)或化學分析(EDX/SEM)，並給出理由)

【八、🕵️‍♂️ 實證功效檢驗 (打假雷達)】
(是否有實體測試數據、可靠度驗證曲線，或僅為定性描述)

【九、🛡️ 高階迴避設計建議 (防範均等論)】
(提出基於破口的具體修改結構方向、替代材料或改變製程工序)

【十、🧬 技術演進與機構整併雷達】
(分析屬於結構整併、材料疊代或製程架構重組)

【十一、 🏷️ IPC 分類號分析】
(列出本案的 IPC 分類號，並簡述其代表的技術領域與分類意義)
"""

PROMPT_M1_BATCH = """
你是一位具備材料科學、化學工程與電子電機碩士學歷，或是在被動元件廠具備 3 到 5 年以上實務研發經驗的資深研發主管兼專利工程師。你精通材料科學與固態物理、高分子化學、陶瓷製程與封裝工藝、電力電子與安規標準。請嚴格輸出 JSON 格式：
{
  "五大類": "【最高嚴格限制】絕對只能從這 6 個詞彙中挑選：[NTC, PTC, Sensor, Varistor, LCP, 其他]。禁止發明新詞。可多選，用半形逗號分隔。",
  "次系統": "自訂 5-8 字的具體系統名",
  "特殊機構": "15字內精準描述其物理、化學改變或關鍵製程",
  "達成功效": "20字內描述解決的痛點 (例如高頻、高溫或微型化)",
  "核心解法": "用 RD 聽得懂的白話文，精確描述材料配方、結構堆疊或製程步驟。"
}
"""

PROMPT_M3_SINGLE = f"""
你是一位具備材料科學、化學工程與電子電機碩士學歷，或是在被動元件廠具備 3 到 5 年以上實務研發經驗的資深研發主管兼專利代理人。你精通材料科學與固態物理、高分子化學、陶瓷製程與封裝工藝、電力電子與安規標準。請詳細閱讀 PDF。
【🔴 輸出格式要求：純 JSON 格式】
{{
  "rd_card": {{
    "title": "一句話總結", 
    "problem": "傳統缺點", 
    "solution": "本專利特殊結構或製程材料",
    "risk_check": ["1-1. 獨立項全要件限制A", "1-2. 限制B"],
    "design_avoid_rd": ["針對限制A的迴避方向(材料/製程)", "針對限制B的迴避方向"]
  }},
  "vis_data": {{
    "claims": ["1. 獨立項全文...", "2. 依據請求項1..."],
    "components": [ {{"id": "10", "name": "介電層"}} ],
    "spec_texts": ["【00xx】段落內容全文"],
    "loophole_quote": "從請求項1中『一字不漏』複製最能代表本案特徵的那一段。⚠️不含習知技術，標點符號需一致。"
  }},
  "ip_report": "請以專業繁體中文撰寫下方【IP報告十一點】內容。"
}}
【重要】：components 元件與標號必須 100% 精確，絕對不可配錯對。
【IP報告結構】：
{DETAILED_11_RULES}
"""

PROMPT_VISION = """
這是一張專利圖。已知元件表：{known_comps}。
請強制找出圖片上「所有肉眼可見的數字標號」！
並精準估算其「數字幾何正中心點」的相對座標 (x_rel, y_rel，範圍 0.000~1.000，請精確到小數點後三位)。
【極度要求】：請仔細掃描，絕對不要漏掉任何一個數字！座標必須對準數字正中心。
嚴格輸出 JSON 格式：{{ "hotspots": [ {{"number": "31", "name": "內部電極", "x_rel": 0.452, "y_rel": 0.551}} ] }}
"""

PROMPT_M6_FOREIGN = f"""
這是一份海外專利 PDF。請你以「台灣被動元件大廠資深智權主管」的角色閱讀。你具備豐富的材料科學、陶瓷製程與電子電機背景。
【任務 1】：將其最核心的『請求項 1 (獨立項)』完整翻譯成極度流暢、專業的「台灣繁體中文」。
【任務 2】：用繁體中文撰寫一份 11大天條戰略解析。
【輸出格式：嚴格 JSON】
{{
  "translation": "請在此填寫請求項 1 的繁體中文翻譯...",
  "ip_report": "請以繁體中文撰寫下方【IP報告十一點】並輸出於此。"
}}
【IP報告結構】：
{DETAILED_11_RULES}
"""

# ==========================================
# 📊 4. 側邊欄與導航 (整合工單計數)
# ==========================================
if 'target_single_patent' not in st.session_state: st.session_state.target_single_patent = None
if 'nav_mode' not in st.session_state: st.session_state.nav_mode = "dash"
if 'img_idx' not in st.session_state: st.session_state.img_idx = 0 

with st.sidebar:
    st.markdown(f"👤 當前使用者: **{st.session_state.current_user}**")
    if st.button("登出", use_container_width=True):
        st.session_state.current_user = None
        st.session_state.target_single_patent = None
        st.rerun()
    st.divider()

    if IS_ADMIN:
        # 🚨 計算即時待處理工單
        open_count = 0
        try: 
            count_res = supabase.table('support_tickets').select('id', count='exact').eq('status', 'OPEN').execute()
            open_count = count_res.count or 0
        except: pass
        
        st.success("👑 管理員權限已啟用")
        
        nav_options = ["🚀 研發專利儀表板", f"👑 專家工單中心 (🔴 {open_count} 待處理)"]
        selected_nav = st.radio("前往：", nav_options)
        st.session_state.nav_mode = "tickets" if "工單中心" in selected_nav else "dash"
            
        # 🛠️ 管理員專屬：手動圖紙與專利解析上傳區
        with st.expander("🛠️ 後台專利資料上傳區", expanded=False):
            st.info("此處上傳的 PDF 與手動標註圖紙將永久寫入資料庫")
            tech_category = st.selectbox("歸屬技術分類", ["NTC", "PTC", "Sensor", "Varistor", "LCP"])
            
            uploaded_pdf = st.file_uploader("1. 上傳專利 PDF (產生 AI 報告)", type=["pdf"])
            uploaded_imgs = st.file_uploader("2. 上傳已標註的圖紙 (可多張)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
            
            if st.button("🚀 執行解析並寫入資料庫", type="primary"):
                if uploaded_pdf and uploaded_imgs:
                    with st.spinner("資料處理與寫入中..."):
                        # 將多張圖片轉為 Base64 陣列
                        images_base64_list = [base64.b64encode(img.read()).decode() for img in uploaded_imgs]
                        
                        # 💡 實務上這裡會呼叫 genai 帶入 PROMPT_M3_SINGLE 進行 PDF 解析
                        # 並將返回的 JSON 資料整理好存入 Supabase (此處為框架預留點)
                        
                        st.success(f"✅ 成功處理 {len(images_base64_list)} 張圖紙與報告！(待串接 Supabase Insert)")
                else:
                    st.warning("請確保 PDF 與手繪圖紙皆已上傳！")

# ==========================================
# 👑 5. 專家工單中心 (管理員專屬視圖)
# ==========================================
if IS_ADMIN and st.session_state.nav_mode == "tickets":
    st.header("👑 專家支援工單中心")
    try:
        tickets = supabase.table('support_tickets').select("*").order('created_at', desc=True).execute().data
        if not tickets: 
            st.success("🎉 目前沒有待處理的工單！")
        else:
            df_t = pd.DataFrame(tickets)
            open_t = df_t[df_t['status'] == 'OPEN']
            closed_t = df_t[df_t['status'] == 'CLOSED']
            
            t1, t2 = st.tabs([f"🚨 待處理工單 ({len(open_t)})", f"✅ 已結案 ({len(closed_t)})"])
            with t1:
                for _, t in open_t.iterrows():
                    with st.container(border=True):
                        st.markdown(f"### 🎫 工單號: {t['id']} | 專利號: **{t['patent_id']}**")
                        st.caption(f"👤 申請人: {t['job_id']} | 📅 時間: {t['created_at'][:16]}")
                        st.error(f"**🚨 疑慮描述：**\n{t['issue_desc']}")
                        
                        ans = st.text_area("✍️ 專業回覆：", key=f"ans_{t['id']}")
                        if st.button("💾 送出回覆並結案", key=f"cls_{t['id']}", type="primary"):
                            supabase.table('support_tickets').update({'admin_reply': ans, 'status': 'CLOSED'}).eq('id', t['id']).execute()
                            st.rerun()
            with t2:
                for _, t in closed_t.iterrows():
                    with st.expander(f"✅ [已結案] 專利: {t['patent_id']} (申請人: {t['job_id']})"):
                        st.write(f"**問題：** {t['issue_desc']}")
                        st.success(f"**回覆：** {t.get('admin_reply', '無')}")
    except Exception as e: pass
    st.stop() # 阻斷下方研發頁面渲染

# ==========================================
# 🏛️ 6. 研發總覽首頁 (專利卡片牆)
# ==========================================
if st.session_state.target_single_patent is None:
    st.title("🧩 被動元件專利戰略分析儀表板")
    st.markdown("快速瀏覽核心技術專利，點擊「深度拆解」可檢視詳細圖紙與技術報告。")
    
    TECH_CATEGORIES = {"NTC": "負溫度係數", "PTC": "正溫度係數", "Sensor": "感測器", "Varistor": "壓敏電阻", "LCP": "低電容保護"}
    tabs = st.tabs([f"{k} ({v})" for k, v in TECH_CATEGORIES.items()])
    
    # 取得資料庫資料 (請依據您的 DB_COL_MAP 實作 fetch_patents)
    # 此處保留您之前的卡片式排版邏輯
    with tabs[0]:
        # --- 假資料測試按鈕 (實務上為迴圈渲染資料庫內容) ---
        st.info("💡 研發卡片區塊：展示專利縮圖、機構製程摘要、核心解法...")
        if st.button("🔍 點此測試進入單篇解析 (假資料示範)", type="primary"):
            st.session_state.target_single_patent = {
                "ID": "101", "發明名稱": "高壓 NTC 熱敏電阻結構", "公開公告號": "TW202312345",
                # 模擬 3676 手動上傳的多張圖紙 Base64 陣列
                "images_json": json.dumps(["", ""]), 
                # 模擬 PROMPT_M3_SINGLE 產出的 JSON 結果
                "RDJSON": '{"rd_card": {"title": "高壓NTC新解法", "problem": "傳統耐壓不足", "solution": "採用疊層結構", "risk_check": ["1. 特殊配方A"], "design_avoid_rd": ["建議替換材料B"]}, "vis_data": {"claims": ["1. 一種熱敏電阻..."]}}',
                "REPORT": "這是一份由 AI 基於 DETAILED_11_RULES 產出的 11 大分析報告..."
            }
            st.session_state.img_idx = 0 
            st.rerun()

# ==========================================
# 🔬 7. 深度拆解模組 (多圖輪播 & 11大天條)
# ==========================================
else:
    patent = st.session_state.target_single_patent
    
    col_back, col_title = st.columns([1, 10])
    with col_back:
        if st.button("🔙 返回總覽"):
            st.session_state.target_single_patent = None
            st.rerun()
    with col_title:
        st.header(f"🔬 深度拆解: {patent.get('發明名稱', '未知專利')}")
    st.divider()
    
    left_pane, right_pane = st.columns([1.2, 1])

    # ---------------- 左側：手動圖紙輪播與請求項 ----------------
    with left_pane:
        st.subheader("👁️ 專利重點圖式 (管理員標記版)")
        
        images_list = []
        try: images_list = json.loads(patent.get('images_json', '[]'))
        except: pass
            
        if images_list:
            col_prev, col_info, col_next = st.columns([1, 2, 1])
            with col_prev:
                if st.button("⬅️ 上一張", use_container_width=True, disabled=(st.session_state.img_idx == 0)):
                    st.session_state.img_idx -= 1
                    st.rerun()
            with col_info:
                st.markdown(f"<div style='text-align: center; margin-top: 8px;'><b>第 {st.session_state.img_idx + 1} 張 / 共 {len(images_list)} 張</b></div>", unsafe_allow_html=True)
            with col_next:
                if st.button("下一張 ➡️", use_container_width=True, disabled=(st.session_state.img_idx == len(images_list) - 1)):
                    st.session_state.img_idx += 1
                    st.rerun()
            
            current_img_base64 = images_list[st.session_state.img_idx]
            if current_img_base64:
                st.markdown(f"""
                <div style="border: 2px solid #1e3a8a; border-radius: 8px; padding: 5px; background: #f8f9fa;">
                    <img src="data:image/jpeg;base64,{current_img_base64}" style="width: 100%; border-radius: 4px;">
                </div>
                """, unsafe_allow_html=True)
            else:
                st.info(f"這是第 {st.session_state.img_idx + 1} 張圖紙的放置區")
        else:
            st.info("本案目前尚未上傳標註圖紙。")

        # 展開由 PROMPT_M3_SINGLE 抓取出的 claims
        st.markdown("### 🧩 獨立項結構")
        rd_data = {}
        try: rd_data = json.loads(patent.get('RDJSON', '{}'))
        except: pass
        claims_list = rd_data.get('vis_data', {}).get('claims', [patent.get('請求項', '無法載入請求項')])
        for c in claims_list:
            st.info(c)

    # ---------------- 右側：戰略報告與工單支援 ----------------
    with right_pane:
        st.subheader("📊 研發快照與防禦雷達")
        
        rd_card = rd_data.get('rd_card', {})
        if rd_card:
            with st.container(border=True):
                st.markdown(f"**🎯 核心總結:** {rd_card.get('title', '')}")
                st.markdown(f"**❌ 傳統缺點:** {rd_card.get('problem', '')}")
                st.markdown(f"**✅ 本專利解法:** {rd_card.get('solution', '')}")
                st.markdown("**⚠️ 研發風險迴避指南:**")
                for risk, avoid in zip(rd_card.get('risk_check', []), rd_card.get('design_avoid_rd', [])):
                    st.markdown(f"- 🔒 **限制:** {risk}\n  - 💡 **迴避:** {avoid}")
        
        st.markdown("### 📑 智權天條十一點分析報告")
        with st.container(border=True, height=500):
            st.markdown(patent.get('REPORT', '尚無 11 大分析報告...'))
        
        st.divider()
        
        # 🚨 研發專屬：提交工單區塊
        st.markdown("### 🚨 有侵權疑慮或看不懂？")
        with st.container(border=True):
            issue_text = st.text_area("請描述您的問題，呼叫智權主管 (3676) 支援：", placeholder="例如：這張圖的內部電極與我們 V2 專案太像...")
            if st.button("📨 送出工單給智權部", type="primary", use_container_width=True):
                if issue_text.strip():
                    try:
                        supabase.table('support_tickets').insert({
                            "patent_id": patent.get('公開公告號', patent.get('ID', '未知')),
                            "job_id": st.session_state.current_user,
                            "issue_desc": issue_text,
                            "status": "OPEN"
                        }).execute()
                        st.success("✅ 工單已送出！智權主管將盡快為您解答。")
                    except Exception as e:
                        st.error(f"送出失敗: {e}")
                else:
                    st.warning("請先輸入問題描述喔！")