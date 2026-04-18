"""
comfyui_bridge.py
─────────────────
Hayeong's ComfyUI integration. Lets her generate images from natural language,
analyze reference images from screen or uploads, and build optimized workflows.

CAPABILITIES:
  - Natural language → ComfyUI prompt translation
  - Screen capture analysis for visual reference
  - Image upload analysis
  - Automatic workflow generation and submission
  - Progress monitoring and result retrieval

USAGE (from main.py or direct):
  bridge = ComfyUIBridge()
  result = bridge.generate("draw Hayeong in the orange frog jacket standing in a park")
  result = bridge.generate_from_screen("make her look like what's on my screen but anime style")
  result = bridge.generate_from_image("path/to/image.jpg", "same style but with blue hair")

TRIGGERS (intent detection):
  "generate", "draw", "make an image", "create a picture", "paint", "illustrate"
  "what does X look like", "show me", "visualize"
  "use what's on my screen", "based on my screen"
"""

import json
import time
import base64
import urllib.request
import urllib.parse
import urllib.error
import requests
import random
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

COMFYUI_URL          = "http://127.0.0.1:8188"
OLLAMA_URL           = "http://localhost:11434/api/chat"
VISION_MODEL_FAST    = "moondream:latest"   # Quick screen grabs — fast, lightweight
VISION_MODEL_DEEP    = "llava:13b"          # Reference image analysis — rich and detailed
LANGUAGE_MODEL       = "qwen2.5:14b"        # Prompt building — strong instruction following
OUTPUT_DIR      = Path(r"H:\ComfyUI_windows_portable\ComfyUI\output")
MODELS_DIR      = Path(r"H:\ComfyUI_windows_portable\ComfyUI\models")

# Default model — change this to whatever Hayeong should use by default
DEFAULT_CHECKPOINT   = "ponyDiffusionV6XL_v6StartWithThisOne.safetensors"
REALISTIC_CHECKPOINT = "epicrealism_naturalSinRC1VAE.safetensors"  # For anime→realistic
IPADAPTER_MODEL      = "ip-adapter_sdxl.safetensors"
CLIP_VISION_MODEL    = "model.safetensors"

BASE_DIR    = Path(__file__).parent
LOG_DIR     = BASE_DIR / "logs"
LOG_FILE    = LOG_DIR / "comfyui_bridge.log"
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ─────────────────────────────────────────────
# PROMPT BUILDER
# Translates natural language into ComfyUI prompts
# ─────────────────────────────────────────────

PROMPT_SYSTEM = """You are Hayeong's image generation assistant. Your job is to translate natural language descriptions into optimized ComfyUI prompts for Pony Diffusion XL.

Pony Diffusion ALWAYS needs these quality tags at the start:
score_9, score_8_up, score_7_up, source_anime,

Rules:
- Always start with the quality tags above
- Be specific about: hair color, eye color, clothing, expression, pose, background
- For anime style use: clean lineart, flat color shading, cel shading, anime screencap style
- Return ONLY a JSON object with these exact keys:
  {
    "positive": "your positive prompt here",
    "negative": "your negative prompt here",
    "width": 832,
    "height": 1216,
    "steps": 28,
    "cfg": 6,
    "sampler": "dpmpp_2m",
    "scheduler": "karras"
  }

For negative always include:
score_1, score_2, score_3, ugly, deformed, bad anatomy, blurry, watermark, low quality, bad hands, extra limbs, poorly drawn face, multiple characters, duplicate

Adjust width/height based on content:
- Portrait/character: 832x1216
- Landscape/scene: 1216x832  
- Square: 1024x1024"""


def build_prompt_from_text(description: str) -> dict:
    """Ask Hayeong's LLM to build an optimized prompt from natural language."""
    log(f"Building prompt from: {description}")
    
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": LANGUAGE_MODEL,
            "messages": [
                {"role": "system", "content": PROMPT_SYSTEM},
                {"role": "user", "content": f"Create an image generation prompt for: {description}"}
            ],
            "stream": False
        }, timeout=30)
        
        content = response.json()["message"]["content"]
        
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            prompt_data = json.loads(json_match.group())
            log(f"Prompt built successfully")
            return prompt_data
        else:
            log("Failed to parse JSON from LLM, using defaults")
            return _default_prompt(description)
            
    except Exception as e:
        log(f"Prompt builder error: {e}")
        return _default_prompt(description)


def _default_prompt(description: str) -> dict:
    """Fallback prompt if LLM call fails."""
    return {
        "positive": f"score_9, score_8_up, score_7_up, source_anime, {description}, anime style, high quality, detailed",
        "negative": "score_1, score_2, score_3, ugly, deformed, bad anatomy, blurry, watermark, low quality, bad hands, extra limbs, poorly drawn face, multiple characters",
        "width": 832,
        "height": 1216,
        "steps": 28,
        "cfg": 6,
        "sampler": "dpmpp_2m",
        "scheduler": "karras"
    }


def analyze_image_with_vision(image_path: str, question: str = None, deep: bool = False) -> str:
    """
    Use vision model to analyze an image and extract description.
    
    deep=False → moondream (fast, for screen grabs)
    deep=True  → llava:13b (detailed, for reference image analysis)
    """
    model = VISION_MODEL_DEEP if deep else VISION_MODEL_FAST
    log(f"Analyzing image with {model} ({'deep' if deep else 'fast'} mode): {image_path}")
    
    if not question:
        if deep:
            question = "Describe this image in detail for use as a reference for anime image generation. Focus on: character appearance, hair color and style, eye color and shape, clothing details, pose, art style, color palette, and overall mood. Be very specific and thorough."
        else:
            question = "Briefly describe what's in this image — characters, style, colors, and any notable visual elements."
    
    try:
        # Read and encode image
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        
        timeout = 90 if deep else 30  # llava needs more time
        
        response = requests.post(OLLAMA_URL, json={
            "model": model,
            "messages": [{
                "role": "user",
                "content": question,
                "images": [image_data]
            }],
            "stream": False
        }, timeout=timeout)
        
        description = response.json()["message"]["content"]
        log(f"Vision analysis complete ({model}): {description[:100]}...")
        return description
        
    except Exception as e:
        log(f"Vision analysis error ({model}): {e}")
        return f"Image at {image_path} (vision analysis failed: {e})"


def capture_screen() -> Optional[str]:
    """Take a screenshot and save it temporarily."""
    try:
        import mss
        import mss.tools
        
        screenshot_path = BASE_DIR / "temp_screenshot.png"
        
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # Primary monitor
            screenshot = sct.grab(monitor)
            mss.tools.to_png(screenshot.raw, screenshot.size, output=str(screenshot_path))
        
        log(f"Screenshot saved to {screenshot_path}")
        return str(screenshot_path)
        
    except ImportError:
        log("mss not installed — run: pip install mss")
        return None
    except Exception as e:
        log(f"Screenshot error: {e}")
        return None


# ─────────────────────────────────────────────
# WORKFLOW BUILDER
# Builds ComfyUI workflow JSON
# ─────────────────────────────────────────────

def build_workflow(prompt_data: dict, reference_image_path: str = None) -> dict:
    """Build a ComfyUI workflow JSON from prompt data."""
    
    seed = random.randint(1, 2**31)
    
    # Base workflow — text only (no IPAdapter)
    workflow = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": DEFAULT_CHECKPOINT}
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["1", 1],
                "text": prompt_data["positive"]
            }
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["1", 1],
                "text": prompt_data["negative"]
            }
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": prompt_data.get("width", 832),
                "height": prompt_data.get("height", 1216),
                "batch_size": 1
            }
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "seed": seed,
                "steps": prompt_data.get("steps", 28),
                "cfg": prompt_data.get("cfg", 6),
                "sampler_name": prompt_data.get("sampler", "dpmpp_2m"),
                "scheduler": prompt_data.get("scheduler", "karras"),
                "denoise": 1.0
            }
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["5", 0],
                "vae": ["1", 2]
            }
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["6", 0],
                "filename_prefix": "Hayeong_gen"
            }
        }
    }
    
    # Add IPAdapter if reference image provided
    if reference_image_path and os.path.exists(reference_image_path):
        log(f"Adding IPAdapter with reference: {reference_image_path}")
        
        workflow["8"] = {
            "class_type": "LoadImage",
            "inputs": {"image": reference_image_path}
        }
        workflow["9"] = {
            "class_type": "CLIPVisionLoader",
            "inputs": {"clip_name": CLIP_VISION_MODEL}
        }
        workflow["10"] = {
            "class_type": "IPAdapterModelLoader",
            "inputs": {"ipadapter_file": IPADAPTER_MODEL}
        }
        workflow["11"] = {
            "class_type": "IPAdapterAdvanced",
            "inputs": {
                "model": ["1", 0],
                "ipadapter": ["10", 0],
                "image": ["8", 0],
                "clip_vision": ["9", 0],
                "weight": 0.35,
                "weight_type": "composition",
                "combine_embeds": "concat",
                "start_at": 0.0,
                "end_at": 0.8,
                "embeds_scaling": "V only"
            }
        }
        
        # Reroute KSampler to use IPAdapter model output
        workflow["5"]["inputs"]["model"] = ["11", 0]
    
    return workflow


def build_img2img_workflow(image_path: str, prompt_data: dict, denoise: float = 0.55) -> dict:
    """
    Build a ComfyUI img2img workflow.
    Used for anime → realistic conversion and photo editing.
    
    denoise: 0.4 = stay close to original, 0.55 = balanced, 0.7 = creative
    """
    seed = random.randint(1, 2**31)
    
    workflow = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": REALISTIC_CHECKPOINT}
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["1", 1],
                "text": prompt_data["positive"]
            }
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["1", 1],
                "text": prompt_data["negative"]
            }
        },
        "4": {
            "class_type": "LoadImage",
            "inputs": {"image": image_path}
        },
        "5": {
            "class_type": "VAEEncode",
            "inputs": {
                "pixels": ["4", 0],
                "vae": ["1", 2]
            }
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["5", 0],
                "seed": seed,
                "steps": prompt_data.get("steps", 30),
                "cfg": prompt_data.get("cfg", 7),
                "sampler_name": prompt_data.get("sampler", "dpmpp_2m"),
                "scheduler": prompt_data.get("scheduler", "karras"),
                "denoise": denoise
            }
        },
        "7": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["6", 0],
                "vae": ["1", 2]
            }
        },
        "8": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["7", 0],
                "filename_prefix": "Hayeong_realistic"
            }
        }
    }
    
    return workflow


# ─────────────────────────────────────────────
# COMFYUI API
# Submits workflows and monitors progress
# ─────────────────────────────────────────────

def check_comfyui_running() -> bool:
    """Check if ComfyUI is running."""
    try:
        response = requests.get(f"{COMFYUI_URL}/system_stats", timeout=3)
        return response.status_code == 200
    except:
        return False


def submit_workflow(workflow: dict) -> Optional[str]:
    """Submit workflow to ComfyUI and return prompt_id."""
    try:
        payload = {"prompt": workflow}
        response = requests.post(
            f"{COMFYUI_URL}/prompt",
            json=payload,
            timeout=10
        )
        result = response.json()
        
        if "prompt_id" in result:
            prompt_id = result["prompt_id"]
            log(f"Workflow submitted — prompt_id: {prompt_id}")
            return prompt_id
        else:
            log(f"Submission failed: {result}")
            return None
            
    except Exception as e:
        log(f"Submission error: {e}")
        return None


def wait_for_completion(prompt_id: str, timeout: int = 300) -> bool:
    """Wait for a generation to complete."""
    log(f"Waiting for completion of {prompt_id}...")
    start = time.time()
    
    while time.time() - start < timeout:
        try:
            response = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=5)
            history = response.json()
            
            if prompt_id in history:
                status = history[prompt_id]
                if "outputs" in status and status["outputs"]:
                    log(f"Generation complete!")
                    return True
                    
        except Exception as e:
            log(f"Status check error: {e}")
        
        time.sleep(2)
    
    log(f"Generation timed out after {timeout}s")
    return False


def get_latest_output(prefix: str = "Hayeong_gen") -> Optional[str]:
    """Get the path to the most recently generated image."""
    try:
        output_files = list(OUTPUT_DIR.glob(f"{prefix}*.png"))
        if output_files:
            latest = max(output_files, key=lambda f: f.stat().st_mtime)
            return str(latest)
        return None
    except Exception as e:
        log(f"Output retrieval error: {e}")
        return None


# ─────────────────────────────────────────────
# MAIN BRIDGE CLASS
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# HAYEONG'S CHARACTER PROMPT
# Proven base prompt for generating Hayeong.
# Used by generate_self() and as the starting point for character design sessions.
# ─────────────────────────────────────────────

HAYEONG_BASE_PROMPT = (
    "score_9, score_8_up, score_7_up, source_anime, "
    "short dark navy blue hair, side swept bangs, longer front bangs, "
    "bright blue eyes, soft pale skin, light freckles across nose and cheeks, "
    "orange frog hoodie hood down, hood resting on back, "
    "clean lineart, flat color shading, cel shading, anime screencap style, "
    "single character, looking at viewer"
)

HAYEONG_BASE_NEGATIVE = (
    "score_1, score_2, score_3, ugly, deformed, bad anatomy, blurry, "
    "watermark, low quality, bad hands, extra limbs, poorly drawn face, "
    "multiple characters, duplicate, hood up"
)


class ComfyUIBridge:
    """
    Hayeong's ComfyUI integration layer.
    Handles all image generation requests, including iterative collaboration.
    """

    def __init__(self):
        self.running = check_comfyui_running()
        self._session_state = {
            "last_positive_prompt":   "",
            "last_image_path":        "",
            "last_visual_impression": "",   # what she actually saw in the last output
            "iteration_count":        0,
            "session_description":    "",   # what James said this session is for
        }
        if self.running:
            log("ComfyUI bridge initialized — ComfyUI is running")
        else:
            log("ComfyUI bridge initialized — ComfyUI is NOT running")
    
    
    def is_available(self) -> bool:
        """Check if ComfyUI is available."""
        self.running = check_comfyui_running()
        return self.running
    
    
    def generate(self, description: str) -> dict:
        """
        Generate an image from a natural language description.
        
        Returns:
            {
                "success": bool,
                "image_path": str or None,
                "prompt_used": str,
                "message": str   ← Hayeong's response to tell James
            }
        """
        if not self.is_available():
            return {
                "success": False,
                "image_path": None,
                "prompt_used": None,
                "message": "ComfyUI isn't running right now. Start it first and I'll generate the image for you!"
            }
        
        log(f"Starting generation: {description}")
        
        # Build prompt
        prompt_data = build_prompt_from_text(description)
        
        # Build workflow
        workflow = build_workflow(prompt_data)
        
        # Submit
        prompt_id = submit_workflow(workflow)
        if not prompt_id:
            return {
                "success": False,
                "image_path": None,
                "prompt_used": prompt_data["positive"],
                "message": "I had trouble submitting the workflow to ComfyUI. Something might be wrong with the connection."
            }
        
        # Wait
        success = wait_for_completion(prompt_id)
        if not success:
            return {
                "success": False,
                "image_path": None,
                "prompt_used": prompt_data["positive"],
                "message": "The generation took too long and timed out. ComfyUI might be struggling."
            }
        
        # Get result
        image_path = get_latest_output("Hayeong_gen")

        # Vision analysis — she looks at what actually rendered
        visual_impression = self._vision_check(image_path)

        self._session_state["last_positive_prompt"]   = prompt_data["positive"]
        self._session_state["last_image_path"]        = image_path or ""
        self._session_state["last_visual_impression"] = visual_impression
        self._session_state["iteration_count"]        = 0

        return {
            "success":           True,
            "image_path":        image_path,
            "prompt_used":       prompt_data["positive"],
            "visual_impression": visual_impression,
            "message":           f"Done! Saved to {image_path}.",
        }
    
    
    def generate_from_image(self, image_path: str, description: str = "") -> dict:
        """
        Generate an image using a reference image + optional description.
        Hayeong will analyze the image and use it as visual reference.
        """
        if not self.is_available():
            return {
                "success": False,
                "image_path": None,
                "message": "ComfyUI isn't running right now!"
            }
        
        # Analyze the reference image — use deep mode for uploaded references
        log(f"Analyzing reference image: {image_path}")
        visual_description = analyze_image_with_vision(image_path, deep=True)
        
        # Combine with user description
        full_description = visual_description
        if description:
            full_description += f". Additionally: {description}"
        
        # Build prompt from combined description
        prompt_data = build_prompt_from_text(full_description)
        
        # Build workflow WITH reference image
        workflow = build_workflow(prompt_data, reference_image_path=image_path)
        
        # Submit and wait
        prompt_id = submit_workflow(workflow)
        if not prompt_id:
            return {"success": False, "image_path": None, "message": "Failed to submit to ComfyUI."}
        
        success = wait_for_completion(prompt_id)
        image_output = get_latest_output("Hayeong_gen") if success else None
        
        return {
            "success": success,
            "image_path": image_output,
            "prompt_used": prompt_data["positive"],
            "visual_analysis": visual_description,
            "message": f"I analyzed your reference image and generated based on it! Saved to {image_output}" if success else "Generation failed."
        }
    
    
    def generate_from_screen(self, description: str = "") -> dict:
        """
        Take a screenshot, analyze it, and generate based on what's on screen.
        """
        if not self.is_available():
            return {
                "success": False,
                "image_path": None,
                "message": "ComfyUI isn't running right now!"
            }
        
        # Capture screen
        screenshot_path = capture_screen()
        if not screenshot_path:
            return {
                "success": False,
                "image_path": None,
                "message": "I couldn't take a screenshot. Make sure mss is installed: pip install mss"
            }
        
        # Analyze screen with fast moondream model
        log("Analyzing screen with moondream (fast mode)")
        visual_description = analyze_image_with_vision(screenshot_path, deep=False)
        
        full_description = visual_description
        if description:
            full_description += f". Additionally: {description}"
        
        prompt_data = build_prompt_from_text(full_description)
        workflow = build_workflow(prompt_data, reference_image_path=screenshot_path)
        
        prompt_id = submit_workflow(workflow)
        if not prompt_id:
            return {"success": False, "image_path": None, "message": "Failed to submit to ComfyUI."}
        
        success = wait_for_completion(prompt_id)
        image_output = get_latest_output("Hayeong_gen") if success else None
        
        message = f"I took a screenshot, analyzed it with moondream, and generated based on it! Saved to {image_output}" if success else "Generation failed."
        return {
            "success": success,
            "image_path": image_output,
            "prompt_used": prompt_data["positive"],
            "visual_analysis": visual_description,
            "message": message
        }
    
    
    def make_realistic(self, image_path: str, description: str = "", denoise: float = 0.55) -> dict:
        """
        Convert an anime image to a photorealistic version.
        
        image_path: path to the anime image
        description: optional extra description e.g. "make her look Korean, early 20s"
        denoise: 0.4=stay close, 0.55=balanced, 0.7=more creative
        """
        if not self.is_available():
            return {
                "success": False,
                "image_path": None,
                "message": "ComfyUI isn't running right now!"
            }
        
        if not os.path.exists(image_path):
            return {
                "success": False,
                "image_path": None,
                "message": f"I can't find the image at {image_path}"
            }
        
        log(f"Converting anime to realistic: {image_path} (denoise={denoise})")
        
        # Analyze the anime image to understand what's in it
        log("Analyzing anime image with llava:13b...")
        visual_description = analyze_image_with_vision(image_path, deep=True)
        
        # Build a realistic prompt from the analysis
        realistic_prompt_request = f"Convert this anime character to a photorealistic human. Analysis: {visual_description}"
        if description:
            realistic_prompt_request += f". Additional instructions: {description}"
        
        # Override system prompt for realistic generation
        realistic_system = """You are an expert at converting anime descriptions to photorealistic image generation prompts for epiCRealism XL.

Rules:
- NO anime/cartoon tags
- Focus on: photorealistic, natural lighting, real human features
- Keep hair and eye colors but make them realistic
- Return ONLY a JSON object:
{
  "positive": "photorealistic, [description], natural lighting, detailed skin, 4k, high quality photography",
  "negative": "anime, cartoon, drawing, illustration, 3d render, cgi, ugly, deformed, blurry, watermark",
  "steps": 30,
  "cfg": 7,
  "sampler": "dpmpp_2m",
  "scheduler": "karras"
}"""

        try:
            response = requests.post(OLLAMA_URL, json={
                "model": LANGUAGE_MODEL,
                "messages": [
                    {"role": "system", "content": realistic_system},
                    {"role": "user", "content": realistic_prompt_request}
                ],
                "stream": False
            }, timeout=30)
            
            content = response.json()["message"]["content"]
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                prompt_data = json.loads(json_match.group())
            else:
                prompt_data = {
                    "positive": f"photorealistic, young woman, {description}, natural lighting, detailed skin, 4k, high quality photography, realistic eyes",
                    "negative": "anime, cartoon, drawing, illustration, 3d render, cgi, ugly, deformed, blurry, watermark, bad anatomy",
                    "steps": 30,
                    "cfg": 7,
                    "sampler": "dpmpp_2m",
                    "scheduler": "karras"
                }
        except Exception as e:
            log(f"Prompt build error: {e}")
            prompt_data = {
                "positive": f"photorealistic, young woman, natural lighting, detailed skin, 4k, high quality photography",
                "negative": "anime, cartoon, drawing, illustration, 3d render, cgi, ugly, deformed, blurry, watermark",
                "steps": 30,
                "cfg": 7,
                "sampler": "dpmpp_2m",
                "scheduler": "karras"
            }
        
        # Build and submit img2img workflow
        workflow = build_img2img_workflow(image_path, prompt_data, denoise=denoise)
        
        prompt_id = submit_workflow(workflow)
        if not prompt_id:
            return {"success": False, "image_path": None, "message": "Failed to submit to ComfyUI."}
        
        success = wait_for_completion(prompt_id)
        image_output = get_latest_output("Hayeong_realistic") if success else None
        
        return {
            "success": success,
            "image_path": image_output,
            "prompt_used": prompt_data["positive"],
            "denoise_used": denoise,
            "message": f"Done! I converted the anime image to realistic and saved it to {image_output}." if success else "Conversion failed."
        }


    def _vision_check(self, image_path: str) -> str:
        """Run moondream on a generated image. Returns description or empty string."""
        if not image_path or not os.path.exists(image_path):
            return ""
        try:
            desc = analyze_image_with_vision(
                image_path,
                question=(
                    "Describe this anime image honestly and specifically. "
                    "Focus on: hair color and style, eye color and expression, "
                    "clothing details (especially hood position — is it up or down?), "
                    "skin tone, any freckles, overall pose and mood. "
                    "Be direct about what's working and what looks off."
                ),
                deep=False,   # moondream — fast, non-competing with ComfyUI
            )
            # analyze_image_with_vision returns an error string rather than raising
            return "" if "vision analysis failed" in desc else desc
        except Exception as e:
            log(f"Vision check error: {e}")
            return ""

    def suggest_prompt_improvements(self, current_prompt: str, feedback: str) -> dict:
        """
        Given feedback on a generated image, return structured prompt changes.
        Returns {"add_positive": str, "add_negative": str, "remove_positive": str, "reasoning": str}
        """
        try:
            response = requests.post(OLLAMA_URL, json={
                "model": LANGUAGE_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an expert ComfyUI prompt engineer for Pony Diffusion XL. "
                            "Given feedback about a generated image, return a JSON object with: "
                            "add_positive (tags to add to positive prompt), "
                            "add_negative (tags to add to negative prompt), "
                            "remove_positive (tags to remove from positive prompt), "
                            "reasoning (one sentence explaining the changes). "
                            "Return ONLY valid JSON. No markdown, no explanation."
                        )
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Current positive prompt: {current_prompt}\n\n"
                            f"Feedback about the image: {feedback}\n\n"
                            f"What prompt changes will fix this?"
                        )
                    }
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
            }, timeout=30)

            parsed = json.loads(response.json()["message"]["content"])
            return {
                "add_positive":    parsed.get("add_positive",    ""),
                "add_negative":    parsed.get("add_negative",    ""),
                "remove_positive": parsed.get("remove_positive", ""),
                "reasoning":       parsed.get("reasoning",       ""),
            }
        except Exception as e:
            log(f"Prompt improvement error: {e}")
            return {"add_positive": "", "add_negative": "", "remove_positive": "", "reasoning": ""}

    def _apply_improvements(self, base_prompt: str, improvements: dict) -> dict:
        """Apply structured prompt improvements to a base prompt."""
        positive = base_prompt

        # Remove tags
        for tag in improvements.get("remove_positive", "").split(","):
            tag = tag.strip()
            if tag:
                positive = positive.replace(tag, "").replace(",,", ",").strip(", ")

        # Add positive tags
        add_pos = improvements.get("add_positive", "").strip()
        if add_pos:
            positive = positive.rstrip(", ") + ", " + add_pos

        # Build negative — start from base negative and add any new negatives
        negative = HAYEONG_BASE_NEGATIVE
        add_neg  = improvements.get("add_negative", "").strip()
        if add_neg:
            negative = negative.rstrip(", ") + ", " + add_neg

        return {
            "positive":  positive,
            "negative":  negative,
            "width":     832,
            "height":    1216,
            "steps":     30,
            "cfg":       6,
            "sampler":   "dpmpp_2m",
            "scheduler": "karras",
        }

    def iterate(self, feedback: str, previous_prompt: str = None) -> dict:
        """
        Refine the last generation based on feedback.

        feedback:        James's comment on what to change
        previous_prompt: The positive prompt from the last generation.
                         If None, loads from session state.

        Returns same shape as generate(), plus "changes_made".
        """
        if not self.is_available():
            return {"success": False, "image_path": None,
                    "message": "ComfyUI isn't running."}

        if not previous_prompt:
            previous_prompt = self._session_state.get("last_positive_prompt", "")

        if not previous_prompt:
            return {"success": False, "image_path": None,
                    "message": "I don't have a previous prompt to iterate from. Generate something first."}

        improvements    = self.suggest_prompt_improvements(previous_prompt, feedback)
        new_prompt_data = self._apply_improvements(previous_prompt, improvements)

        log(f"Iterating — changes: {improvements.get('reasoning', '')}")
        log(f"New positive: {new_prompt_data['positive'][:120]}")

        workflow  = build_workflow(new_prompt_data)
        prompt_id = submit_workflow(workflow)
        if not prompt_id:
            return {"success": False, "image_path": None,
                    "message": "Failed to submit refined generation."}

        success    = wait_for_completion(prompt_id)
        image_path = get_latest_output("Hayeong_gen") if success else None

        prev_impression = self._session_state.get("last_visual_impression", "")
        visual_impression = self._vision_check(image_path) if success else ""

        if success:
            self._session_state["last_positive_prompt"]   = new_prompt_data["positive"]
            self._session_state["last_image_path"]        = image_path or ""
            self._session_state["last_visual_impression"] = visual_impression
            self._session_state["iteration_count"]        = \
                self._session_state.get("iteration_count", 0) + 1

        count = self._session_state.get("iteration_count", 1)
        return {
            "success":           success,
            "image_path":        image_path,
            "prompt_used":       new_prompt_data.get("positive", ""),
            "changes_made":      improvements.get("reasoning", "Refined based on feedback."),
            "visual_impression": visual_impression,
            "prev_impression":   prev_impression,
            "message": (
                f"Iteration {count} done. "
                f"{improvements.get('reasoning', 'Refined based on feedback.')} "
                f"Saved to {image_path}."
            ) if success else "Iteration failed.",
        }

    def generate_self(self, additional_description: str = "") -> dict:
        """
        Generate Hayeong using her established character prompt.
        Starting point for character design sessions.

        additional_description: optional context ("standing in a park",
                                 "looking confident", etc.)
        """
        if not self.is_available():
            return {"success": False, "image_path": None,
                    "message": "ComfyUI isn't running."}

        prompt = HAYEONG_BASE_PROMPT
        if additional_description:
            prompt += f", {additional_description.strip().strip(',')}"

        prompt_data = {
            "positive":  prompt,
            "negative":  HAYEONG_BASE_NEGATIVE,
            "width":     832,
            "height":    1216,
            "steps":     30,
            "cfg":       6,
            "sampler":   "dpmpp_2m",
            "scheduler": "karras",
        }

        log(f"Generating self — prompt: {prompt[:120]}")

        workflow  = build_workflow(prompt_data)
        prompt_id = submit_workflow(workflow)
        if not prompt_id:
            return {"success": False, "image_path": None,
                    "message": "Failed to submit."}

        success    = wait_for_completion(prompt_id)
        image_path = get_latest_output("Hayeong_gen") if success else None

        visual_impression = self._vision_check(image_path) if success else ""

        if success:
            self._session_state["last_positive_prompt"]   = prompt_data["positive"]
            self._session_state["last_image_path"]        = image_path or ""
            self._session_state["last_visual_impression"] = visual_impression
            self._session_state["iteration_count"]        = 0

        return {
            "success":           success,
            "image_path":        image_path,
            "prompt_used":       prompt_data["positive"],
            "visual_impression": visual_impression,
            "message": f"Generated. Saved to {image_path}." if success else "Generation failed.",
        }


# ─────────────────────────────────────────────
# INTENT INTEGRATION
# Add this to intent_detector.py INTENT_DEFINITIONS
# ─────────────────────────────────────────────

IMAGE_GENERATION_INTENT = {
    "image_generation": {
        "description": "Any request to generate, draw, create, or visualize an image. Also triggers when James asks Hayeong to use screen or reference images.",
        "examples": [
            "generate an image of",
            "draw me",
            "create a picture of",
            "make an image",
            "visualize",
            "show me what X looks like",
            "use what's on my screen",
            "generate based on this image",
            "paint",
            "illustrate",
            "what would X look like"
        ],
        "keywords": [
            "generate", "draw", "paint", "illustrate", "image", "picture",
            "visualize", "show me", "create art", "make her look",
            "what does", "what would", "on my screen", "from this image"
        ]
    }
}

# ─────────────────────────────────────────────
# MAIN.PY INTEGRATION SNIPPET
# Add this to main.py's intent handling section
# ─────────────────────────────────────────────

MAIN_PY_SNIPPET = '''
# ── Add near top of main.py imports ──
from comfyui_bridge import ComfyUIBridge
comfyui = ComfyUIBridge()

# ── Add to intent handling in main loop ──
elif intent["intent"] == "image_generation":
    action = intent.get("action", "generate")
    
    # Anime to realistic conversion
    if any(x in user_input.lower() for x in ["make realistic", "make it realistic", "realistic version", "real person", "turn into real"]):
        speak("I'll analyze the image and convert it to a realistic photo. Give me a moment.")
        image_path = input("Path to the anime image: ").strip()
        result = comfyui.make_realistic(image_path)
    
    # Generate from screen
    elif any(x in user_input.lower() for x in ["screen", "on my screen", "what's on my screen"]):
        speak("Let me take a look at your screen and work from that.")
        result = comfyui.generate_from_screen(user_input)
    
    # Generate from reference image
    elif any(x in user_input.lower() for x in ["this image", "this photo", "from this", "based on this"]):
        speak("What image would you like me to use as reference?")
        image_path = input("Image path: ").strip()
        result = comfyui.generate_from_image(image_path, user_input)
    
    # Pure text generation
    else:
        speak("On it! Let me generate that for you.")
        result = comfyui.generate(user_input)
    
    if result["success"]:
        speak(f"Done! I saved it to the output folder.")
    else:
        speak(result.get("message", "Something went wrong with the generation."))
'''


# ─────────────────────────────────────────────
# STANDALONE TEST
# Run this file directly to test the bridge
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("ComfyUI Bridge — Standalone Test")
    print("=" * 50)
    
    bridge = ComfyUIBridge()
    
    if not bridge.is_available():
        print("❌ ComfyUI is not running!")
        print("Start it first with: run_nvidia_gpu.bat")
        exit(1)
    
    print("✅ ComfyUI is running!")
    print()
    
    # Test generation
    test_description = input("Enter a description to generate (or press Enter for default): ").strip()
    if not test_description:
        test_description = "Hayeong, anime girl, short dark navy blue hair, bright blue eyes, freckles, orange frog hoodie hood down, gentle expression, white background"
    
    print(f"\nGenerating: {test_description}")
    print("This may take a moment...")
    
    result = bridge.generate(test_description)
    
    if result["success"]:
        print(f"\n✅ Success!")
        print(f"Image saved to: {result['image_path']}")
        print(f"Prompt used: {result['prompt_used'][:150]}...")
    else:
        print(f"\n❌ Failed: {result['message']}")