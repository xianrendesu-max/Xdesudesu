import re
import httpx
import feedparser
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Optional
from pydantic import BaseModel

app = FastAPI(title="X-Viewer Proxy Service")

# CORS設定: ブラウザからの直接リクエストを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2026年時点で比較的安定しているNitterインスタンスのリスト
# インスタンスが死んでいる場合はここを更新してください
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.cz",
    "https://nitter.it",
    "https://nitter.net"
]

# APIのレスポンスモデル定義
class Tweet(BaseModel):
    id: str
    author: str
    content: str
    image: Optional[str] = None
    link: str
    published: str

class TweetResponse(BaseModel):
    instance: str
    data: List[Tweet]

# --- ヘルパー関数 ---
def clean_html(raw_html: str) -> str:
    """HTMLタグを除去してテキストのみにする"""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.strip()

def extract_image(description: str) -> Optional[str]:
    """RSSのdescription内から最初の画像URLを抽出する"""
    # NitterのRSSは <img src="..."> 形式で画像を含んでいる
    img_match = re.search(r'<img[^>]+src="([^">]+)"', description)
    if img_match:
        url = img_match.group(1)
        # プロトコルが抜けている場合は補完
        if url.startswith("//"):
            url = "https:" + url
        return url
    return None

# --- APIエンドポイント ---

@app.get("/api/tweets", response_model=TweetResponse)
async def get_tweets(q: str, type: str = "user"):
    """
    Nitterからツイートを取得するメインエンドポイント
    q: ユーザー名 または 検索キーワード
    type: 'user' または 'search'
    """
    path = q.replace('@', '') if type == "user" else f"search?q={q}"
    
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for base_url in NITTER_INSTANCES:
            try:
                rss_url = f"{base_url}/{path}/rss"
                response = await client.get(rss_url, timeout=7.0)
                
                if response.status_code == 200:
                    feed = feedparser.parse(response.text)
                    
                    if not feed.entries:
                        continue # エントリが空なら次のインスタンスへ

                    tweets = []
                    for entry in feed.entries:
                        tweets.append(Tweet(
                            id=entry.id,
                            author=entry.author if 'author' in entry else q,
                            content=clean_html(entry.description),
                            image=extract_image(entry.description),
                            link=entry.link,
                            published=entry.published
                        ))
                    
                    return TweetResponse(instance=base_url, data=tweets)
            except Exception as e:
                print(f"Error connecting to {base_url}: {e}")
                continue
                
    raise HTTPException(status_code=503, detail="すべてのNitterインスタンスが一時的に利用不可、またはデータが見つかりません。")

# --- 静的ファイルの設定 ---

# /static ディレクトリを配信可能にする
# 注: 事前に 'static' フォルダを作成し index.html を入れておく必要があります
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    """ルートにアクセスした時にフロントエンドを表示"""
    return FileResponse('static/index.html')

if __name__ == "__main__":
    import uvicorn
    # Render等の環境で動作させるための起動設定
    uvicorn.run(app, host="0.0.0.0", port=10000)

