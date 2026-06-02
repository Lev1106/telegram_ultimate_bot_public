from imports import *
from config import *

async def news(update: Update, context: CallbackContext):
    url = 'https://tengrinews.kz/ajax/get/audio-news/'
    news_list = requests.get(url).json()
    result = ''
    for new in news_list:
        new_date = datetime.strptime(new['news_publish_date'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=5)))
        diff = datetime.now(timezone(timedelta(hours=5))) - new_date
        cur = f'• <a href="{new["chpu"]}">{new["title"]}</a> ({new["news_publish_date"]}) (/content{new["object_id"]}) (/comments{new["object_id"]})\n\n'
        if len(result) + len(cur) < MAX_MESSAGE_LENGTH:
            result += cur
        else:
            break
    await update.message.reply_text(result, parse_mode='HTML')

async def new_content(update: Update, context: CallbackContext):
    id = update.message.text.replace("/content", "")
    id = id.replace("", "")
    url = f'https://tengrinews.kz/ajax/get/material/{id}/News/1/'
    content = requests.get(url).json()['data']
    await update.message.reply_text(content)#, parse_mode='HTML')
    # await update.message.reply_text(content, parse_mode='HTML')

async def new_comments(update: Update, context: CallbackContext):
    id = update.message.text.replace("/comments", "")
    id = id.replace("", "")
    url = f'https://c.tn.kz/comments/get/list/?id={id}&type=news&lang=ru&sort=best'
    print(id)
    content = requests.get(url).json()
    comment_list = []
    for comment in content['list']:
        comment_str = f':flag_{comment["ip_country"].lower()}: <b>{comment["name"]}</b>: {comment["text"]}\n'
        comment_list.append(comment_str)

    result = ''
    for comment in comment_list:
        if len(result) + len(comment) < MAX_MESSAGE_LENGTH:
            result += comment
        else:
            break

    if len(result) == 0:
        result = 'No'

    result = result.replace(':flag_kz:', '🇰🇿')
    result = result.replace(':flag_ru:', '🇷🇺')

    await update.message.reply_text(result, parse_mode='HTML')