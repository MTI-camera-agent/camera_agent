"""
功能：
1. 加载指定的 VLM 模型，为每张图片生成中文图像编辑指令。
2. 加载指定的 Qwen-Image-Edit-2511 图像编辑模型。
3. 从 image_dir 读取原图，按“生成编辑指令 -> 执行图像编辑”的顺序逐张串联推理。
4. 将编辑后的图片保存到 edited_dir 目录下，文件名与原图保持一致。
"""

import os
os.environ["CUDA_VISIBLE_DEVICES"] = "6,7,8,9"

import json
import torch
from transformers import AutoModelForImageTextToText, AutoProcessor
from tqdm import tqdm
from PIL import Image
from diffusers import QwenImageEditPlusPipeline
from io import BytesIO
import requests

model_path = ".../checkpoint-78"  # VLM 模型权重路径
qwen_edit_model_path = ".../Qwen-Image-Edit-2511"  # Qwen-Image-Edit-2511 模型权重路径
image_dir = "..."  # 原图目录
edited_dir = "..."  # 编辑后图片保存目录

os.makedirs(edited_dir, exist_ok=True)

# We recommend enabling flash_attention_2 for better acceleration and memory saving, especially in multi-image and video scenarios.
model = AutoModelForImageTextToText.from_pretrained(model_path, dtype=torch.bfloat16, attn_implementation="flash_attention_2", device_map="auto",)
#model = AutoModelForImageTextToText.from_pretrained(model_path, dtype=torch.bfloat16, device_map="auto",)
processor = AutoProcessor.from_pretrained(model_path)

pipeline = QwenImageEditPlusPipeline.from_pretrained(qwen_edit_model_path, torch_dtype=torch.bfloat16, device_map="balanced")
print("pipeline loaded")

#pipeline.to('cuda')
pipeline.set_progress_bar_config(disable=None)

# ===== 读取数据 =====
image_names = sorted(
    file_name for file_name in os.listdir(image_dir)
    if os.path.isfile(os.path.join(image_dir, file_name))
)


question = "Based on this photo, generate one image editing instruction for aesthetic reconstruction. Keep the subject's appearance and scene content unchanged, and improve the photo's aesthetics only by adjusting factors such as viewpoint, composition, and human pose. You may only operate on elements already present in the photo, and must not introduce, assume, or describe any new people, objects, or scene elements."
for image_name in tqdm(image_names, desc="Running benchmark"):
    poor_image = os.path.join(image_dir, image_name)

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "image": poor_image,
                },
                {"type": "text", "text": question},
            ],
        }
    ]

    # Preparation for inference
    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt"
    )
    inputs = inputs.to(model.device)

    # Inference: Generation of the output
    generated_ids = model.generate(**inputs, max_new_tokens=500, do_sample=False)
    generated_ids_trimmed = [
        out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]
    output_text = processor.batch_decode(
        generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )
    prompt = output_text[0]

    print(f"{image_name}: {prompt}")

    image_path = os.path.join(image_dir, image_name)
    image1 = Image.open(image_path).convert("RGB")

    inputs = {
        "image": [image1],
        "prompt": prompt,
        "generator": torch.manual_seed(0),
        "true_cfg_scale": 4.0,
        "negative_prompt": " ",
        "num_inference_steps": 40,
        "guidance_scale": 1.0,
        "num_images_per_prompt": 1,
    }
    with torch.inference_mode():
        output = pipeline(**inputs)
        output_image = output.images[0]
        output_path = os.path.join(edited_dir, image_name)
        output_image.save(output_path)
        print("image saved at", output_path)

print(f"Total images: {len(image_names)}")
