import redis
from dotenv import load_dotenv
import os
load_dotenv()
# r = redis.Redis(host=os.getenv('REDIS_HOST'), port=os.getenv('REDIS_PORT'), db=0, decode_responses=True,password=os.getenv('REDIS_PASSWORD'))