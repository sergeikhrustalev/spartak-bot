import feedparser
import requests
import os
import hashlib
import json
import time
import re
import socket
from datetime import datetime, timezone, timedelta

socket.setdefaulttimeout(10)

BOT_TOKEN = os.environ['BOT_TOKEN']
CHANNEL = '@bozhespartakhranii'

SPARTAK_KEYWORDS = [
    'спартак', 'spartak', 'красно-белые', 'народная команда',
]

SOURCES = [
    {
        'name': 'Чемпионат',
        'url': 'https://www.championat.com/rss/news/',
        'filter': True,
    },
    {
        'name': 'ТАСС',
        'url': 'https://tass.ru/rss/v2.xml',
        'filter': True,
    },
    {
        'name': 'Google Новости',
        'url': 'https://news.google.com/rss/search?q=%D0%A1%D0%BF%D0%B0%D1%80%D1%82%D0%B0%D0%BA+%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B0&hl=ru&gl=RU&ceid=RU:ru',
        'filter': False,
    },
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; SpartakNewsBot/1.0)'
}


def is_spartak_related(text):
    return any(kw in text.lower() for kw in SPARTAK_KEYWORDS)


def clean_html(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def format_post(title, summary, source_name, pub_dt):
    time_str = pub_dt.strftime('%H:%M') if pub_dt else ''
    text = f'🔴⚪️ <b>{title}</b>'
    if summary:
        clean = clean_html(summary)[:400].strip()
        if len(clean_html(summary)) > 400:
            clean += '...'
        text += f'\n\n{clean}'
    text += f'\n\n📰 {source_name}'
    if time_str:
        text += f' | 🕐 {time_str} МСК'
    return text


def send_message(text):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    resp = requests.post(url, json={
        'chat_id': CHANNEL,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    })
    if not resp.ok:
        print(f'Telegram error: {resp.text}')
    return resp.ok


def get_article_id(url):
    return hashlib.md5(url.encode()).hexdigest()


def load_posted():
    if os.path.exists('posted.json'):
        with open('posted.json') as f:
            return set(json.load(f))
    return set()


def save_posted(posted):
    with open('posted.json', 'w') as f:
        json.dump(list(posted), f)


def main():
    posted = load_posted()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=26)

    new_articles = []

    for source in SOURCES:
        try:
            feed = feedparser.parse(
                source['url'],
                request_headers=HEADERS,
            )
            if feed.bozo and not feed.entries:
                print(f'Feed error {source["name"]}: {feed.bozo_exception}')
                continue

            for entry in feed.entries:
                title = entry.get('title', '').strip()
                url = entry.get('link', '').strip()
                summary = entry.get('summary', entry.get('description', ''))

                if not title or not url:
                    continue

                if source['filter']:
                    if not is_spartak_related(title + ' ' + summary):
                        continue

                article_id = get_article_id(url)
                if article_id in posted:
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
                    'summary': summary,
                    'source': source['name'],
                    'pub_dt': pub_dt,
                })

        except Exception as e:
            print(f'Error fetching {source["name"]} ({source["url"]}): {e}')

    seen_titles = set()
    unique_articles = []
    for a in new_articles:
        title_key = a['title'].lower()[:60]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_articles.append(a)

    unique_articles.sort(key=lambda x: x['pub_dt'])

    to_post = unique_articles[:4]

    if not to_post:
        print('No new Spartak articles found.')
        save_posted(posted)
        return

    # Spread posts evenly over 28 minutes
    # 1 article → post immediately
    # N articles → interval = 28min / (N-1) between each
    WINDOW = 28 * 60  # seconds
    interval = WINDOW / (len(to_post) - 1) if len(to_post) > 1 else 0

    posted_count = 0
    for i, article in enumerate(to_post):
        if i > 0:
            print(f'Waiting {int(interval)} sec before next post...')
            time.sleep(interval)

        text = format_post(
            article['title'],
            article['summary'],
            article['source'],
            article['pub_dt'],
        )
        if send_message(text):
            posted.add(article['id'])
            posted_count += 1
            print(f'Posted: {article["title"]}')

    print(f'Done. Posted {posted_count} articles.')

    save_posted(posted)


if __name__ == '__main__':
    main()
