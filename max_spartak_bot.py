import feedparser
import requests
import trafilatura
import os
import hashlib
import json
import time
import re
import socket
from datetime import datetime, timezone, timedelta

socket.setdefaulttimeout(15)

ACCESS_TOKEN = os.environ['ACCESS_TOKEN']
CHAT_ID = int(os.environ.get('CHAT_ID', '-72873687632407'))

MAX_API = 'https://botapi.max.ru'

SOURCES = [
    {
        'name': 'Чемпионат',
        'url': 'https://www.championat.com/rss/news/',
        'filter': True,
    },
    {
        'name': 'Чемпионат',
        'url': 'https://www.championat.com/rss/article/spartak/',
        'filter': False,
    },
]

SPARTAK_KEYWORDS = ['спартак', 'spartak', 'красно-белые']

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

TEXT_LIMIT = 3500


def is_spartak_related(text):
    return any(kw in text.lower() for kw in SPARTAK_KEYWORDS)


def clean_text(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    text = text.replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'")
    text = text.replace('&laquo;', '«').replace('&raquo;', '»')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def fetch_article_text(url):
    try:
        r = requests.get(url, timeout=12, headers=HEADERS)
        if not r.ok:
            return ''
        text = trafilatura.extract(
            r.text,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if not text:
            return ''
        if len(text) > TEXT_LIMIT:
            chunk = text[:TEXT_LIMIT]
            last_dot = chunk.rfind('.')
            if last_dot > TEXT_LIMIT // 2:
                chunk = chunk[:last_dot + 1]
            else:
                chunk = chunk.rstrip() + '...'
            return chunk
        return text
    except Exception as e:
        print(f'Text fetch error for {url}: {e}')
        return ''


def format_post(title, body, source_name, pub_dt):
    msk = timezone(timedelta(hours=3))
    time_str = pub_dt.astimezone(msk).strftime('%H:%M') if pub_dt else ''
    text = f'🔴⚪️ {title}'
    if body:
        text += f'\n\n{body}'
    text += f'\n\n📰 {source_name}'
    if time_str:
        text += f' | 🕐 {time_str} МСК'
    return text


def send_message(text, chat_id):
    import json as _json
    try:
        resp = requests.post(
            f'{MAX_API}/messages',
            params={'chat_id': chat_id},
            data=_json.dumps({'text': text}).encode('utf-8'),
            headers={
                'Authorization': ACCESS_TOKEN,
                'Content-Type': 'application/json',
            },
            timeout=15,
        )
        if not resp.ok:
            print(f'MAX API error: {resp.status_code} {resp.text}')
        else:
            print(f'MAX API ok')
        return resp.ok
    except Exception as e:
        print(f'Send error: {e}')
        return False


def get_article_id(url):
    return hashlib.md5(url.encode()).hexdigest()


def load_posted():
    fname = 'posted_max.json'
    if os.path.exists(fname):
        with open(fname) as f:
            return set(json.load(f))
    return set()


def save_posted(posted):
    with open('posted_max.json', 'w') as f:
        json.dump(list(posted), f)


def main():
    chat_id = CHAT_ID
    posted = load_posted()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=26)

    new_articles = []

    for source in SOURCES:
        try:
            feed = feedparser.parse(source['url'], request_headers=HEADERS)
            if feed.bozo and not feed.entries:
                print(f'Feed error {source["name"]}: {feed.bozo_exception}')
                continue

            for entry in feed.entries:
                title = clean_text(entry.get('title', '').strip())
                url = entry.get('link', '').strip()
                summary = entry.get('summary', entry.get('description', ''))

                if not title or not url:
                    continue

                article_id = get_article_id(url)
                if article_id in posted:
                    continue

                if source['filter']:
                    if not is_spartak_related(title + ' ' + summary):
                        continue

                pub = entry.get('published_parsed')
                if pub:
                    try:
                        pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    except Exception:
                        pub_dt = now
                else:
                    pub_dt = now

                if pub_dt < cutoff:
                    continue

                new_articles.append({
                    'id': article_id,
                    'title': title,
                    'url': url,
                    'source': source['name'],
                    'pub_dt': pub_dt,
                })

        except Exception as e:
            print(f'Error fetching {source["name"]}: {e}')

    seen_titles = set()
    unique_articles = []
    for a in new_articles:
        key = re.sub(r'\W+', '', a['title'].lower())[:50]
        if key not in seen_titles:
            seen_titles.add(key)
            unique_articles.append(a)

    unique_articles.sort(key=lambda x: x['pub_dt'])
    to_post = unique_articles[:4]

    if not to_post:
        print('No new Spartak articles found.')
        save_posted(posted)
        return

    WINDOW = 28 * 60
    interval = WINDOW / (len(to_post) - 1) if len(to_post) > 1 else 0

    posted_count = 0
    for i, article in enumerate(to_post):
        if i > 0:
            time.sleep(interval)

        body = fetch_article_text(article['url'])
        text = format_post(article['title'], body, article['source'], article['pub_dt'])
        if send_message(text, chat_id):
            posted.add(article['id'])
            posted_count += 1
            print(f'Posted: {article["title"]}')

    print(f'Done. Posted {posted_count} articles.')
    save_posted(posted)


if __name__ == '__main__':
    main()
