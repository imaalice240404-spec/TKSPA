import os
import time
from supabase import create_client, Client

S_URL = os.getenv("SUPABASE_URL")
S_KEY = os.getenv("SUPABASE_KEY")

if not S_URL or not S_KEY:
    print("❌ 錯誤：找不到 SUPABASE_URL 或 SUPABASE_KEY 環境變數。")
    exit(1)

supabase: Client = create_client(S_URL, S_KEY)

def keep_alive():
    print("🚀 正在執行 Supabase Keep Alive 任務...")
    dummy_data = {
        "app_num": "KEEP_ALIVE_TEST",
        "title": "SYSTEM_KEEP_ALIVE",
        "status": "KEEP_ALIVE",
        "abstract": "This is an automated request to prevent the project from pausing."
    }
    try:
        insert_response = supabase.table('patents').insert(dummy_data).execute()
        inserted_id = insert_response.data[0]['id']
        print(f"✅ 成功寫入假資料，ID: {inserted_id}")
        time.sleep(2)
        supabase.table('patents').delete().eq('id', inserted_id).execute()
        print(f"✅ 成功刪除假資料，ID: {inserted_id}")
        print("🎉 Keep Alive 任務執行完畢！Supabase 專案已標記為活躍。")
    except Exception as e:
        print(f"❌ 執行 Keep Alive 任務時發生錯誤：{e}")

if __name__ == "__main__":
    keep_alive()
