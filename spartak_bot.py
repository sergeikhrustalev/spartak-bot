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

SOURCES = [
    {
        'name': 'Google Новости',
        'url': 'https://news.google.com/rss/search?q=%D0%A1%D0%BF%D0%B0%D1%80%D1%82%D0%B0%D0%BA+%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B0&hl=ru&gl=RU&ceid=RU:ru',
        'is_google': True,
    },
    {
        'name': 'ТАСС',
        'url': 'https://tass.ru/rss/v2.xml',
        'is_google': False,
        'filter': True,
    },
]

SPARTAK_KEYWORDS = ['спартак', 'spartak', 'красно-белые']

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; SpartakNewsBot/1.0)'
}

# Маппинг доменов в читаемые названия (чтобы Telegram не делал их кликабельными ссылками)
DOMAIN_MAP = {
    'championat.ru': 'Чемпионат',
    'championat.com': 'Чемпионат',
    'sport-express.ru': 'Спорт-Экспресс',
    'sports.ru': 'Sports.ru',
    'tass.ru': 'ТАСС',
    'ria.ru': 'РИА Новости',
    'rsport.ria.ru': 'РИА Спорт',
    'sport24.ru': 'Sport24',
    'soccer.ru': 'Soccer.ru',
    'bombardir.ru': 'Bombardir',
    'sovsport.ru': 'Советский Спорт',
    'matchtv.ru': 'Матч ТВ',
    'gazeta.ru': 'Газета.ру',
    'rbc.ru': 'РБК',
    'interfax.ru': 'Интерфакс',
    'lenta.ru': 'Лента.ру',
    'kommersant.ru': 'Коммерсантъ',
    'iz.ru': 'Известия',
    'mk.ru': 'МК',
    'euro-football.ru': 'Евро-Футбол',
    'football.ru': 'Football.ru',
    'rusfootball.info': 'Рус. Футбол',
    'spartak.com': 'Спартак офиц.',
    'fanat1k.ru': 'Фанат1к',
    'bombardir.ru': 'Bombardir',
    'transfermarkt.ru': 'Transfermarkt',
}


def clean_source_name(raw):
    """Converts 'championat.ru' → 'Чемпионат', leaves 'Евро-Футбол' as is."""
    raw = raw.strip()
    raw_lower = raw.lower()
    # Direct match
    if raw_lower in DOMAIN_MAP:
        return DOMAIN_MAP[raw_lower]
    # Partial match
    for domain, name in DOMAIN_MAP.items():
        if domain in raw_lower:
            return name
    # Looks like a domain (no spaces, has dot) — strip TLD
    if '.' in raw and ' ' not in raw:
        return raw.split('.')[0].capitalize()
    return raw


def is_spartak_related(text):
    return any(kw in text.lower() for kw in SPARTAK_KEYWORDS)


def clean_text(text):
    """Strip HTML tags and decode HTML entities."""
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = text.replace('&laquo;', '«')
    text = text.replace('&raquo;', '»')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_google_title(raw_title):
    """
    Google News titles: 'Текст статьи - Источник'
    Returns: (clean_title, source_name)
    """
    # Split on last ' - ' to separate source
    parts = raw_title.rsplit(' - ', 1)
    if len(parts) == 2:
        title = parts[0].strip()
        source = clean_source_name(parts[1].strip())
        return title, source
    return raw_title.strip(), 'Новости'


def format_post(title, source_name, pub_dt):
    """Format a clean Telegram post. No description, no links."""
    msk = timezone(timedelta(hours=3))
    time_str = pub_dt.astimezone(msk).strftime('%H:%M') if pub_dt else ''
    # Escape < > & in title to avoid breaking HTML parse_mode
    title = title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = f'🔴⚪️ <b>{title}</b>'
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
            feed = feedparser.parse(source['url'], request_headers=HEADERS)
            if feed.bozo and not feed.entries:
                print(f'Feed error {source["name"]}: {feed.bozo_exception}')
                continue

            for entry in feed.entries:
                raw_title = entry.get('title', '').strip()
                url = entry.get('link', '').strip()

                if not raw_title or not url:
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

                if source['is_google']:
                    title, source_name = parse_google_title(clean_text(raw_title))
                else:
                    title = clean_text(raw_title)
                    source_name = source['name']
                    summary = entry.get('summary', entry.get('description', ''))
                    if not is_spartak_related(title + ' ' + summary):
                        continue

                new_articles.append({
                    'id': article_id,
                    'title': title,
                    'source': source_name,
                    'pub_dt': pub_dt,
                })

        except Exception as e:
            print(f'Error fetching {source["name"]}: {e}')

    # Deduplicate by normalised title
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
            print(f'Waiting {int(interval)} sec before next post...')
            time.sleep(interval)

        text = format_post(article['title'], article['source'], article['pub_dt'])
        if send_message(text):
            posted.add(article['id'])
            posted_count += 1
            print(f'Posted: {article["title"]}')

    print(f'Done. Posted {posted_count} articles.')
    save_posted(posted)


if __name__ == '__main__':
    main()
