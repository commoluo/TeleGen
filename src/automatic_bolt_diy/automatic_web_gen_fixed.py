import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

def automatic_web_gen(idx, instruction, download_dir="downloads", url="http://localhost:5173/",
    desired_model="gpt-4o", provider="OpenAI"):
    print(f"Running automatic_web_gen with idx={idx}, instruction='{instruction}', download_dir='{download_dir}', url='{url}', desired_model='{desired_model}', provider='{provider}'")
    
    # Set up Chrome & download folder
    download_dir = os.path.abspath(download_dir)
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    if os.path.exists(os.path.join(download_dir, f"{idx:06d}.json")) and os.path.exists(os.path.join(download_dir, f"{idx:06d}.zip")):
        print(f"Files {idx:06d}.json and {idx:06d}.zip already exist. Skipping download.")
        return

    from selenium.webdriver.chrome.options import Options
    chrome_options = Options()
    
    # Set window size and download preferences
    chrome_options.add_argument("--window-size=1920,1080")
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    driver = webdriver.Chrome(options=chrome_options)

    try:
        driver.get(url)
        wait = WebDriverWait(driver, 30)
        print("Page loaded, waiting for elements...")

        # Wait for page to be fully loaded
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "select")))
        time.sleep(3)

        # STEP A: Select the provider in the first dropdown
        print(f"Selecting provider: {provider}")
        try:
            provider_select_element = driver.find_element(
                By.CSS_SELECTOR, 
                "select.flex-1.p-2.rounded-lg.border"
            )
            provider_select = Select(provider_select_element)
            
            # Check available options
            available_options = [option.get_attribute('value') for option in provider_select.options]
            print(f"Available provider options: {available_options}")
            
            if provider in available_options:
                provider_select.select_by_value(provider)
                print(f"Selected provider: {provider}")
            else:
                print(f"Provider '{provider}' not found in options: {available_options}")
                # Try to select the first available option
                if available_options:
                    provider_select.select_by_value(available_options[0])
                    print(f"Selected first available provider: {available_options[0]}")
            
            time.sleep(2)  # Wait for provider change to take effect
            
        except Exception as e:
            print(f"Error selecting provider: {e}")
            # Continue anyway

        # STEP B: Select the model in the combobox
        print(f"Selecting model: {desired_model}")
        try:
            # Click on the combobox to open it
            combobox = wait.until(EC.element_to_be_clickable((
                By.CSS_SELECTOR,
                'div[role="combobox"]'
            )))
            combobox.click()
            print("Clicked combobox")
            time.sleep(2)

            # Wait for the listbox to appear
            try:
                wait.until(EC.visibility_of_element_located((By.ID, "model-listbox")))
                print("Model listbox appeared")
                
                # Look for the specific model option
                option_locator = (
                    By.XPATH,
                    f'//div[@id="model-listbox"]//div[@role="option" and contains(text(), "{desired_model}")]'
                )
                
                # Try to find and click the option
                try:
                    option_element = wait.until(EC.element_to_be_clickable(option_locator))
                    option_element.click()
                    print(f"Selected model: {desired_model}")
                except TimeoutException:
                    print(f"Model '{desired_model}' not found, trying to select any available option...")
                    # Get all available options
                    options = driver.find_elements(By.XPATH, '//div[@id="model-listbox"]//div[@role="option"]')
                    if options:
                        print(f"Available models: {[opt.text for opt in options[:5]]}")  # Show first 5
                        options[0].click()  # Select the first one
                        print(f"Selected first available model: {options[0].text}")
                    else:
                        print("No model options found")
                        
            except TimeoutException:
                print("Model listbox did not appear, continuing without model selection...")
                
        except Exception as e:
            print(f"Error with model selection: {e}")
            # Continue anyway

        # STEP C: Enter text in the chat box
        print("Entering instruction in textarea...")
        try:
            text_box = wait.until(EC.element_to_be_clickable((By.TAG_NAME, "textarea")))
            text_box.clear()
            text_box.send_keys(instruction)
            text_box.send_keys(Keys.ENTER)
            print("Instruction sent")
        except Exception as e:
            print(f"Error entering instruction: {e}")
            return

        # STEP D: Wait for response to be generated
        print("Waiting for response generation...")
        try:
            # Wait for response generation to complete (with shorter timeout)
            wait_long = WebDriverWait(driver, 300)  # 5 minutes
            
            # Look for various indicators that response is complete
            completion_indicators = [
                "//div[contains(text(), 'Response Generated')]",
                "//div[contains(text(), 'Complete')]", 
                "//div[contains(text(), 'Done')]",
                "//button[contains(text(), 'Download Code')]",
                "//button[contains(text(), 'Code')]",
                "//div[contains(@class, 'preview')]",
                "//iframe[contains(@src, 'preview')]"
            ]
            
            response_found = False
            for indicator in completion_indicators:
                try:
                    element = driver.find_element(By.XPATH, indicator)
                    if element and element.is_displayed():
                        print(f"Found completion indicator: {indicator}")
                        response_found = True
                        break
                except:
                    continue
            
            if not response_found:
                # If no indicators found, wait a bit and check for any new content
                print("No specific completion indicators found, waiting for content...")
                time.sleep(30)  # Wait 30 seconds for content to generate
                
        except TimeoutException:
            print("Response generation timed out, but continuing...")

        time.sleep(10)  # Extra wait to ensure everything is loaded

        # STEP E: Look for and click the "Code" button
        print("Looking for Code button...")
        try:
            # Try multiple selectors for the Code button
            code_button_selectors = [
                "//button[.//span[text()='Code']]",
                "//button[contains(text(), 'Code')]",
                "//button[@title='Code']",
                "//button[contains(@class, 'code')]"
            ]
            
            code_button = None
            for selector in code_button_selectors:
                try:
                    code_button = driver.find_element(By.XPATH, selector)
                    break
                except NoSuchElementException:
                    continue
            
            if code_button:
                code_button.click()
                print("Clicked Code button")
                time.sleep(2)
            else:
                print("Code button not found")
                
        except Exception as e:
            print(f"Error with Code button: {e}")

        # STEP F: Download Code
        print("Looking for Download Code button...")
        try:
            download_selectors = [
                "//button[contains(text(), 'Download Code')]",
                "//button[contains(text(), 'Download')]",
                "//button[@title='Download Code']"
            ]
            
            files_before = set(os.listdir(download_dir))
            download_button = None
            
            for selector in download_selectors:
                try:
                    download_button = driver.find_element(By.XPATH, selector)
                    break
                except NoSuchElementException:
                    continue
            
            if download_button:
                download_button.click()
                print("Clicked Download Code button")
                time.sleep(5)
                
                # Check for new files
                files_after = set(os.listdir(download_dir))
                new_files = files_after - files_before
                if len(new_files) == 1:
                    downloaded_file = new_files.pop()
                    old_path = os.path.join(download_dir, downloaded_file)
                    zip_name = f"{idx:06d}.zip"
                    new_path = os.path.join(download_dir, zip_name)
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    os.rename(old_path, new_path)
                    print(f"Renamed code file to: {new_path}")
                else:
                    print(f"Found {len(new_files)} new files after download: {new_files}")
            else:
                print("Download Code button not found")
                
        except Exception as e:
            print(f"Error downloading code: {e}")

        # STEP G: Export Chat
        print("Looking for Export Chat button...")
        try:
            export_selectors = [
                "//button[@title='Export Chat']",
                "//button[contains(text(), 'Export')]",
                "//button[contains(@class, 'export')]"
            ]
            
            files_before = set(os.listdir(download_dir))
            export_button = None
            
            for selector in export_selectors:
                try:
                    export_button = driver.find_element(By.XPATH, selector)
                    break
                except NoSuchElementException:
                    continue
            
            if export_button:
                export_button.click()
                print("Clicked Export Chat button")
                time.sleep(5)
                
                # Check for new files
                files_after = set(os.listdir(download_dir))
                new_files = files_after - files_before
                if len(new_files) == 1:
                    downloaded_file = new_files.pop()
                    old_path = os.path.join(download_dir, downloaded_file)
                    json_name = f"{idx:06d}.json"
                    new_path = os.path.join(download_dir, json_name)
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    os.rename(old_path, new_path)
                    print(f"Renamed chat file to: {new_path}")
                else:
                    print(f"Found {len(new_files)} new files after export: {new_files}")
            else:
                print("Export Chat button not found")
                
        except Exception as e:
            print(f"Error exporting chat: {e}")

        time.sleep(2)
        print("Automation completed")

    finally:
        driver.quit()

if __name__ == "__main__":
    # Test with a simple instruction using GPT-4o
    automatic_web_gen(
        idx=1, 
        instruction="Create a simple hello world webpage with a blue background and centered text",
        download_dir="downloads",
        desired_model="gpt-4o",
        provider="OpenAI"
    )
