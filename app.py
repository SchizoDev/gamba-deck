import gradio as gr
import requests
import json
import settings_manager
import sys

# Add sound playback support
try:
    import playsound
except ImportError:
    import subprocess
    def playsound(sound_path):
        if sys.platform.startswith('win'):
            subprocess.Popen(['powershell', '-c', f'(New-Object Media.SoundPlayer "{sound_path}").PlaySync();'])
        else:
            subprocess.Popen(['aplay', sound_path])

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# List of available models (example, update as needed)
MODEL_OPTIONS = [
    "openai/gpt-3.5-turbo",
    "openai/gpt-4",
    "google/gemini-pro",
    "anthropic/claude-3-opus"
]

def greet(name):
    return f"Hello, {name}!"

def chat_with_openrouter(message, model, api_key):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": model,
        "messages": [
            {"role": "user", "content": message}
        ]
    }
    response = requests.post(OPENROUTER_API_URL, headers=headers, json=data)
    if response.status_code == 200:
        result = response.json()
        return result['choices'][0]['message']['content']
    else:
        return f"Error: {response.status_code} - {response.text}"

def gambling_deck(url, model, api_key, debug=False):
    debug_info = {}
    try:
        import time
        import re
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.common.exceptions import NoSuchElementException, WebDriverException
        # Set up headless Chrome with necessary options
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')  # Disable sandbox for Windows
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-dev-shm-usage')
        max_attempts = 4
        for attempt in range(max_attempts):
            try:
                driver = webdriver.Chrome(options=options)
                driver.get(url)
                time.sleep(5)  # Wait for the page to load completely
                question_element = driver.find_element(By.TAG_NAME, 'h1')
                question = question_element.text.strip() if question_element else url
                # Try to click 'View more' if present
                try:
                    view_more_btn = driver.find_element(By.XPATH, "//p[contains(text(), 'View more')]")
                    if view_more_btn:
                        view_more_btn.click()
                        time.sleep(1)
                except NoSuchElementException:
                    pass
                # Extract outcomes: only <p> tags with a percentage, stop at 'OUTCOME'
                outcomes = []
                p_elements = driver.find_elements(By.TAG_NAME, 'p')
                outcome_re = re.compile(r'(\d{1,3}(?:\.\d+)?%|<\s*1%)')
                for el in p_elements:
                    text = el.text.strip()
                    if text.upper().startswith('OUTCOME'):
                        break
                    if outcome_re.search(text):
                        # Remove the percentage or <1% from the outcome
                        outcome_text = outcome_re.sub('', text)
                        # Remove any trailing/leading '<', '>', or whitespace
                        outcome_text = outcome_text.strip(' <>').strip()
                        if outcome_text and outcome_text not in outcomes:
                            outcomes.append(outcome_text)
                driver.quit()
                if not outcomes:
                    return question, 'Not enough volume/data to make a prediction.', ''
                outcomes_str = ', '.join(outcomes)
                debug_info['scraped_question'] = question
                debug_info['scraped_outcomes'] = outcomes
                break
            except WebDriverException as e:
                if attempt == max_attempts - 1:
                    return f"Error: Could not reach website after {max_attempts} attempts: {e}", '', ''
                time.sleep(2)
            except Exception as e:
                return f"Error: {e}", '', ''
    except Exception as e:
        debug_info['error'] = f"Error fetching or parsing Polymarket page: {e}"
        return f"Error fetching or parsing Polymarket page: {e}", '', ''

    prompt = f"""
You are an expert probabilistic reasoner.
Given the following question and possible outcomes, estimate the probability of each outcome (as a percentage, summing to 100%).

Question: {question}
Possible outcomes (comma separated): {outcomes_str}

Return your answer as a JSON object with one key: 'probabilities' (a dict of outcome: probability).
"""
    debug_info['prompt'] = prompt
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    debug_info['llm_request'] = data
    response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
    debug_info['llm_status_code'] = response.status_code
    try:
        debug_info['llm_response'] = response.json()
    except Exception as e:
        debug_info['llm_response'] = f"Error decoding LLM response: {e}"
    if response.status_code == 200:
        try:
            result = response.json()
            content = result['choices'][0]['message']['content']
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                json_str = match.group(0)
                parsed = json.loads(json_str)
                probabilities = parsed['probabilities']
                if not isinstance(probabilities, dict) or not probabilities:
                    debug_info['error'] = "No valid probabilities returned."
                    return "No valid probabilities returned.", '', ''
                best_outcome = max(probabilities, key=probabilities.get)
                best_percentage = probabilities[best_outcome]
                percents = list(probabilities.values())
                even_warning = ""
                if len(percents) > 1 and max(percents) - sorted(percents)[-2] < 10:
                    even_warning = " Warning: The probabilities are too even. No clear favorite."
                bet_on_text = f"{best_outcome}{even_warning}"
                percent_success_text = f"{best_percentage}%"
                all_probs_text = ", ".join([f"{k}: {v}%" for k, v in probabilities.items()])
                return bet_on_text, percent_success_text, all_probs_text
            else:
                debug_info['error'] = f"Could not find JSON in LLM response. Raw: {content}"
                return f"Error: Could not find JSON in LLM response. Raw: {content}", '', ''
        except Exception as e:
            debug_info['error'] = f"Could not parse LLM response: {e}"
            return f"Error: Could not parse LLM response: {e}", '', ''
    else:
        debug_info['error'] = f"Error: {response.status_code} - {response.text}"
        return f"Error: {response.status_code} - {response.text}", '', ''

with gr.Blocks(theme='NoCrypt/miku') as iface:
    # Replace checkbox with a button and use a session state to not show warning again
    import gradio as gr
    from gradio.routes import Request
    
    def show_main_app():
        return gr.update(visible=True), gr.update(visible=False)

    main_app_group = gr.Group(visible=False)
    warning_group = gr.Group(visible=True)
    with warning_group:
        gr.Markdown(
            '''
            🚨 **SKIBIDI WARNING!** 🚨

            This app is a giga-meme coded by "SchizoDev" (yes, that's the name) and is **NOT financial advice**. If you trust your hard-earned money to this goofy ahh program, you are officially a skibidi sigma NPC. This code is actual toilet water. If you lose money, that's on you, not SchizoDev, not your mom, not the government.

            By clicking the button below, you accept that:
            - This is a joke.
            - You will probably lose money if you ignore this.
            - You can't sue, cry, or mald at SchizoDev.

            Skibidi rizz out. You have been warned.
            '''
        )
        gr.Markdown("<br><br>")
        rizz_audio = gr.Audio(
            value=None,
            visible=False,
            interactive=False,
            label=None,
            autoplay=True
        )
        accept_btn = gr.Button("I have read and accept the Skibidi Warning above")
    with main_app_group:
        gr.Markdown("# Gamba Deck")
        def get_selected_model():
            try:
                with open("selected_model.txt", "r") as f:
                    return f.read().strip()
            except Exception:
                return "anthropic/claude-sonnet-4:online"
        with gr.Tab("Gamba Deck"):
            with gr.Row():
                gd_url = gr.Textbox(label="Sketchy Gamba Site URL", 
                                   info="Paste the full URL of a market to analyze its outcomes.",
                                   show_label=True)
                model_options = [
                    ("anthropic/claude-sonnet-4:online", "Anthropic Claude Sonnet 4 (default)"),
                    ("google/gemini-2.5-flash-preview-05-20", "Google Gemini 2.5 Flash Preview 05-20"),
                    ("openai/gpt-4o-mini", "OpenAI GPT-4o Mini"),
                    ("google/gemini-2.5-pro-preview", "Google Gemini 2.5 Pro Preview")
                ]
                gd_model = gr.Dropdown(
                    choices=[m[0] for m in model_options],
                    value="anthropic/claude-sonnet-4:online",
                    label="AI Model",
                    info="Choose which AI model to use for estimating outcome probabilities."
                )
                gamblecore_audio = gr.Audio(
                    value=None,
                    visible=False,
                    interactive=False,
                    label=None,
                    autoplay=True
                )
                gd_btn = gr.Button("Predict!")
            with gr.Row():
                bet_on = gr.Textbox(label="What to bet on", interactive=False, 
                                   info="The outcome with the highest estimated probability, based on the AI model.")
                percent_success = gr.Textbox(label="Percentage of success", interactive=False, 
                                            info="The estimated probability (in %) for the most likely outcome.")
            with gr.Row():
                piechart = gr.Plot(label="Probabilities Pie Chart")
            def run_gambling_deck(url, model):
                api_key = settings_manager.load_api_key()
                result = gambling_deck(url, model, api_key, False)
                # Prepare pie chart if probabilities are available
                try:
                    all_probs_str = result[2]
                    if all_probs_str:
                        import matplotlib.pyplot as plt
                        labels = []
                        sizes = []
                        for part in all_probs_str.split(','):
                            if ':' in part:
                                k, v = part.split(':')
                                labels.append(k.strip())
                                sizes.append(float(v.strip().replace('%','')))
                        fig, ax = plt.subplots()
                        ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90)
                        ax.axis('equal')
                        return result[0], result[1], fig, gr.update(value="assets/sounds/gamblecore.opus")
                except Exception:
                    pass
                return result[0], result[1], None, gr.update(value="assets/sounds/gamblecore.opus")
            gd_btn.click(
                fn=run_gambling_deck,
                inputs=[gd_url, gd_model],
                outputs=[bet_on, percent_success, piechart, gamblecore_audio]
            )
        with gr.Tab("Settings"):
            gr.Markdown("## API Key Management")
            settings_api_key = gr.Textbox(label="OpenRouter API Key", type="password", value=settings_manager.load_api_key(),
                                         info="Enter your OpenRouter API key here. This is required to use the AI models.")
            spear_goblins_audio = gr.Audio(
                value=None,
                visible=False,
                interactive=False,
                label=None,
                autoplay=True
            )
            save_btn = gr.Button("Save API Key")
            settings_status = gr.Markdown()
            def save_key(api_key):
                try:
                    settings_manager.save_api_key(api_key)
                    return "**API key saved and encrypted!**", gr.update(value="assets/sounds/goblin.opus")
                except Exception as e:
                    return f"Error saving API key: {e}", gr.update(value="assets/sounds/goblin.opus")
            save_btn.click(fn=save_key, inputs=[settings_api_key], outputs=[settings_status, spear_goblins_audio])
        with gr.Tab("Credits"):
            gr.Markdown('''
# Credits

**Developer:**  
**SchizoDev**  
[YouTube](https://www.youtube.com/@SchizoDev/) | [Patreon](https://patreon.com/SchizoDev) | [Discord](https://discord.gg/chWagUEHb3) | [Twitter](https://twitter.com/SchizoDev_)

**Patrons:**

*Thank you to all the patrons for funding the SchizoDev channel, which made this project possible!*

---

## Uooooooh
- **Boop Doop**
- **nezuko_777**

---

## Uooh
- **Anatidae**
- **Whisper**

---

## Uoh
- **Crayons-are-life**
- **dibus**
- **SuperSex420.69**
- **Nursehella Esq.**
- **Hag Lover**
- **mipancreas**
''')
            wysi_audio = gr.Audio(
                value=None,
                visible=False,
                interactive=False,
                label=None,
                autoplay=True
            )
            wysi_btn = gr.Button("Secret WYSI", visible=True)
            def play_wysi():
                return gr.update(value="assets/sounds/727.opus")
            wysi_btn.click(play_wysi, outputs=[wysi_audio])
    def accept_warning():
        return gr.update(visible=True), gr.update(visible=False), gr.update(value="assets/sounds/rizz.opus")
    accept_btn.click(accept_warning, outputs=[main_app_group, warning_group, rizz_audio])

if __name__ == "__main__":
    iface.launch()