#!/usr/bin/env python3
"""
Debug script to inspect the Bolt.diy UI structure and find the correct selectors
"""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

def debug_ui():
    # Set up Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--window-size=1920,1080")
    # Don't use headless mode for debugging
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        print("Opening Bolt.diy...")
        driver.get("http://localhost:5173/")
        time.sleep(5)  # Wait for page to load
        
        print("\n=== Page Title ===")
        print(driver.title)
        
        print("\n=== Looking for select elements ===")
        selects = driver.find_elements(By.TAG_NAME, "select")
        print(f"Found {len(selects)} select elements")
        for i, select in enumerate(selects):
            print(f"Select {i}: {select.get_attribute('outerHTML')[:200]}")
        
        print("\n=== Looking for div with role=combobox ===")
        comboboxes = driver.find_elements(By.CSS_SELECTOR, 'div[role="combobox"]')
        print(f"Found {len(comboboxes)} combobox elements")
        for i, cb in enumerate(comboboxes):
            print(f"Combobox {i}: {cb.get_attribute('outerHTML')[:200]}")
        
        print("\n=== Looking for textareas ===")
        textareas = driver.find_elements(By.TAG_NAME, "textarea")
        print(f"Found {len(textareas)} textarea elements")
        for i, ta in enumerate(textareas):
            print(f"Textarea {i}: {ta.get_attribute('outerHTML')[:200]}")
            
        print("\n=== Looking for buttons ===")
        buttons = driver.find_elements(By.TAG_NAME, "button")
        print(f"Found {len(buttons)} button elements")
        for i, btn in enumerate(buttons):
            btn_text = btn.text.strip()
            if btn_text:
                print(f"Button {i}: '{btn_text}' - {btn.get_attribute('class')}")
        
        print("\n=== Page HTML Structure (first 1000 chars) ===")
        print(driver.page_source[:1000])
        
        print("\n=== Debug complete ===")
        time.sleep(2)  # Wait a bit before closing
        
    finally:
        driver.quit()

if __name__ == "__main__":
    debug_ui()
