#!/usr/bin/env python3
"""
更详细的UI调试脚本
"""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

def detailed_debug():
    chrome_options = Options()
    chrome_options.add_argument("--window-size=1920,1080")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        print("Opening Bolt.diy...")
        driver.get("http://localhost:5173/")
        time.sleep(5)
        
        # Check the select element more carefully
        print("\n=== Detailed Select Element Analysis ===")
        try:
            select_element = driver.find_element(By.TAG_NAME, "select")
            print(f"Select found with classes: {select_element.get_attribute('class')}")
            print(f"Select parent: {select_element.find_element(By.XPATH, '..').get_attribute('outerHTML')[:300]}")
            
            # Check options
            options = select_element.find_elements(By.TAG_NAME, "option")
            print(f"Found {len(options)} options:")
            for option in options:
                print(f"  - Value: '{option.get_attribute('value')}', Text: '{option.text}'")
        except Exception as e:
            print(f"Error with select: {e}")
            
        # Check the combobox element
        print("\n=== Detailed Combobox Analysis ===")
        try:
            combobox = driver.find_element(By.CSS_SELECTOR, 'div[role="combobox"]')
            print(f"Combobox classes: {combobox.get_attribute('class')}")
            print(f"Combobox text: '{combobox.text.strip()}'")
            print(f"Combobox innerHTML: {combobox.get_attribute('innerHTML')[:300]}")
        except Exception as e:
            print(f"Error with combobox: {e}")
            
        # Check for model-related elements
        print("\n=== Looking for model-related elements ===")
        model_elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'model') or contains(@class, 'model') or contains(@id, 'model')]")
        print(f"Found {len(model_elements)} model-related elements")
        for elem in model_elements[:5]:  # Show first 5
            print(f"  - Tag: {elem.tag_name}, Text: '{elem.text[:50]}', Class: '{elem.get_attribute('class')}'")
            
        time.sleep(2)
        
    finally:
        driver.quit()

if __name__ == "__main__":
    detailed_debug()
