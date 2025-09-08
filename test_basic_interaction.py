#!/usr/bin/env python3
"""
简单测试脚本，测试基本的UI交互
"""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

def test_basic_interaction():
    print("Starting basic interaction test...")
    
    chrome_options = Options()
    chrome_options.add_argument("--window-size=1920,1080")
    # 不使用headless模式，这样可以看到发生了什么
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        print("Opening Bolt.diy...")
        driver.get("http://localhost:5173/")
        time.sleep(5)
        
        print("Page loaded, looking for elements...")
        wait = WebDriverWait(driver, 10)
        
        # 1. 尝试找到并操作textarea
        print("Looking for textarea...")
        try:
            textarea = wait.until(EC.presence_of_element_located((By.TAG_NAME, "textarea")))
            print("✓ Found textarea")
            
            # 输入简单的指令
            instruction = "Create a simple webpage that says 'Hello World' with a red background"
            textarea.clear()
            textarea.send_keys(instruction)
            print(f"✓ Entered instruction: {instruction}")
            
            # 发送消息
            textarea.send_keys(Keys.ENTER)
            print("✓ Sent message")
            
            # 等待一会儿看响应
            time.sleep(10)
            
            # 检查页面是否有变化
            page_text = driver.find_element(By.TAG_NAME, "body").text
            if "Hello World" in page_text or "red background" in page_text or "generating" in page_text.lower():
                print("✓ Page appears to be processing the request")
            else:
                print("? No obvious signs of processing")
                
        except Exception as e:
            print(f"✗ Error with textarea: {e}")
        
        # 等待更长时间以观察结果
        print("Waiting 30 seconds to observe results...")
        time.sleep(30)
        
        print("Test completed. Closing browser...")
        time.sleep(5)  # Wait 5 seconds to observe
        
    finally:
        driver.quit()

if __name__ == "__main__":
    test_basic_interaction()
