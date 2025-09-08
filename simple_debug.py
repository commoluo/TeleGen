#!/usr/bin/env python3
"""
简化版UI调试 - 直接截图查看
"""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

def simple_debug():
    chrome_options = Options()
    chrome_options.add_argument("--window-size=1920,1080")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        driver.get("http://localhost:5173/")
        time.sleep(5)
        
        # 保存页面截图
        driver.save_screenshot("bolt_ui_screenshot.png")
        print("Screenshot saved as bolt_ui_screenshot.png")
        
        # 尝试找到provider select
        try:
            # 更新的CSS选择器，基于我们发现的类名
            provider_select = driver.find_element(
                By.CSS_SELECTOR, 
                "select.flex-1.p-2.rounded-lg.border"
            )
            print("✓ Found provider select")
            
            # 检查选项
            from selenium.webdriver.support.ui import Select
            select = Select(provider_select)
            options = [option.get_attribute('value') for option in select.options]
            print(f"Provider options: {options}")
            
        except Exception as e:
            print(f"✗ Provider select not found: {e}")
            
        # 尝试找到模型combobox
        try:
            model_combobox = driver.find_element(
                By.CSS_SELECTOR,
                'div[role="combobox"]'
            )
            print("✓ Found model combobox")
            print(f"Combobox text: '{model_combobox.text.strip()}'")
            
        except Exception as e:
            print(f"✗ Model combobox not found: {e}")
            
        # 尝试找到textarea
        try:
            textarea = driver.find_element(By.TAG_NAME, "textarea")
            print("✓ Found textarea")
            print(f"Textarea placeholder: '{textarea.get_attribute('placeholder')}'")
            
        except Exception as e:
            print(f"✗ Textarea not found: {e}")
        
        time.sleep(2)
        
    finally:
        driver.quit()

if __name__ == "__main__":
    simple_debug()
