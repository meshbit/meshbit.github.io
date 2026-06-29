#!/usr/bin/env python3
import re, json, hashlib, time, os, sys, argparse
from datetime import datetime
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
for k in ["HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"]: os.environ.pop(k,None)
import requests
SCRIPT_DIR=os.path.dirname(os.path.abspath(__file__))
HEADERS={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36","Accept":"application/json","Accept-Language":"zh-CN,zh;q=0.9","Referer":"https://www.bilibili.com/","Origin":"https://www.bilibili.com"}