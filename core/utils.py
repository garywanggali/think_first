import os
import requests
import uuid
from django.conf import settings
from django.core.files.base import ContentFile

def save_image_from_url(image_url):
    """
    下载图片并保存到 media/ai_images/ 目录
    返回相对路径 (e.g. /media/ai_images/xxx.png)
    """
    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        
        # 确保目录存在
        save_dir = os.path.join(settings.MEDIA_ROOT, 'ai_images')
        os.makedirs(save_dir, exist_ok=True)
        
        # 生成唯一文件名
        filename = f"{uuid.uuid4()}.png"
        file_path = os.path.join(save_dir, filename)
        
        with open(file_path, 'wb') as f:
            f.write(response.content)
            
        return f"{settings.MEDIA_URL}ai_images/{filename}"
    except Exception as e:
        print(f"Error saving image: {e}")
        return None

def save_uploaded_file(uploaded_file):
    """
    保存上传的文件到 media/user_uploads/ 目录
    """
    try:
        save_dir = os.path.join(settings.MEDIA_ROOT, 'user_uploads')
        os.makedirs(save_dir, exist_ok=True)
        
        ext = os.path.splitext(uploaded_file.name)[1]
        if not ext:
            ext = '.jpg' # Default
            
        filename = f"{uuid.uuid4()}{ext}"
        file_path = os.path.join(save_dir, filename)
        
        with open(file_path, 'wb') as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)
                
        return f"{settings.MEDIA_URL}user_uploads/{filename}", file_path
    except Exception as e:
        print(f"Error saving uploaded file: {e}")
        return None, None