from typing import Optional
from openai import OpenAI
import os


class LLMHandler:
    def __init__(self, api_key: Optional[str] = None):
        """Initialize with HuggingFace API key"""
        self.api_key = api_key or os.environ.get("HUGGINGFACE_API_KEY")
        if not self.api_key:
            raise ValueError("HuggingFace API key is required")

        self.client = OpenAI(
            base_url="https://api-inference.huggingface.co/v1/", api_key=self.api_key
        )
        self.model = "meta-llama/Llama-3.2-3B-Instruct"

    async def llm(
        self, prompt: str, max_tokens: int = 2000, temperature: float = 0.2
    ) -> str:
        """
        Process text with Llama 3.2 model

        Args:
            prompt: Input text to process
            max_tokens: Maximum tokens to generate
            temperature: Temperature for response generation

        Returns:
            Processed text response
        """
        try:
            messages = [{"role": "user", "content": prompt}]

            # Get the completion without streaming
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,  # Disable streaming
            )

            # Extract the response text
            if completion.choices and hasattr(completion.choices[0], "message"):
                return completion.choices[0].message.content
            else:
                raise ValueError("No response content received from the model")

        except Exception as e:
            print(f"Error processing with Llama 3.2: {e}")
            raise
