import os
from dotenv import load_dotenv
from model.factory import chat_model, embed_model


load_dotenv()

print('DeepSeek:', bool(os.getenv('DEEPSEEK_API_KEY'))); print('Amap:', bool(os.getenv('AMAP_API_KEY')))
print(chat_model.invoke('只回答：模型连接正常').content); print(len(embed_model.embed_query('番茄炒鸡蛋')))