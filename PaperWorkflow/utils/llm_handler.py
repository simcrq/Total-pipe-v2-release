from openai import OpenAI
from loguru import logger
import os
import time

class LLMHandler:
    def __init__(self, config):
        self.config = config
        llm_conf = config['api']['llm']
        
        api_key = str(llm_conf.get('api_key') or os.getenv('OPENAI_API_KEY') or '').strip()
        self.model = str(llm_conf.get('model_name') or '').strip()
        base_url = str(llm_conf.get('base_url') or '').strip()
        if not api_key:
            raise ValueError('LLM API key is missing; set api.llm.api_key or OPENAI_API_KEY')
        if not self.model:
            raise ValueError('LLM model_name is missing')

        client_kwargs = {'api_key': api_key}
        if base_url:
            client_kwargs['base_url'] = base_url
        self.client = OpenAI(**client_kwargs)
        self.timeout = llm_conf.get('timeout', 120)
        self.max_retries = int(llm_conf.get('max_retries', 2))

    def summarize(self, prompt_content):
        """
        调用 LLM 进行总结
        """
        logger.info(f"第2/2步:Sending request to LLM {self.model}...")
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a helpful research assistant."},
                        {"role": "user", "content": prompt_content}
                    ],
                    timeout=self.timeout
                )
                content = response.choices[0].message.content
                if not content:
                    raise RuntimeError("LLM returned an empty response")
                return content
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                delay = min(2 ** attempt, 8)
                logger.warning(f"LLM request failed (attempt {attempt + 1}); retrying in {delay}s: {exc}")
                time.sleep(delay)

        logger.error(f"LLM request failed after retries: {last_error}")
        raise RuntimeError(f"LLM request failed after {self.max_retries + 1} attempts") from last_error
