# Podcast-Video-Maker-Workflow

A local presenter: paste a short script, choose a portrait, and get one seated talking-head clip. An example, Blue Hour Desk, is in `examples/`.

The clip is 768×768, 16 fps, and about 5 seconds (one Wan 2.2 S2V chunk of 77 frames). About 12 words fills it. The page submits the graph through the Comfy Developer Platform SDK to ComfyUI on this machine.

Open weights in the graph:

- Wan 2.2 S2V 14B fp8 (`wan2.2_s2v_14B_fp8_scaled.safetensors`)
- umT5 text encoder (`umt5_xxl_fp8_e4m3fn_scaled.safetensors`)
- Wan 2.1 VAE (`wan_2.1_vae.safetensors`)
- wav2vec2 English audio encoder (`wav2vec2_large_english_fp16.safetensors`)
- LightX2V 4-step LoRA (`wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors`)
- Kokoro speech (`bf_emma`, `bf_alice`, `bf_isabella`, `bf_lily`)

Sampling is euler, 4 steps, CFG 1, shift 8. On a 16 GB card one chunk takes about 8 minutes. The LightX2V file is the text-to-video lightning LoRA from the [Comfy Wan 2.2 S2V tutorial](https://docs.comfy.org/tutorials/video/wan/wan2-2-s2v). It is what makes the short take finish. Mouth motion is softer than a 20-step sample.

## What you need

- ComfyUI running at `http://127.0.0.1:8188`
- Python 3.10 or newer
- A portrait you have the right to use. Square, front-facing, and evenly lit works best. A slightly parted mouth helps the first frame.

Model files, from [Comfy-Org/Wan_2.2_ComfyUI_Repackaged](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged) and the [S2V tutorial](https://docs.comfy.org/tutorials/video/wan/wan2-2-s2v):

| File | Folder |
| --- | --- |
| `wan2.2_s2v_14B_fp8_scaled.safetensors` | `models/diffusion_models/` |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `models/text_encoders/` |
| `wan_2.1_vae.safetensors` | `models/vae/` |
| `wav2vec2_large_english_fp16.safetensors` | `models/audio_encoders/` |
| `wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors` | `models/loras/` |

Custom nodes, cloned into `ComfyUI/custom_nodes`, then restart ComfyUI:

```
git clone https://github.com/stavsap/comfyui-kokoro.git
git clone https://github.com/ussoewwin/ComfyUI-DistorchMemoryManager.git
```

Kokoro downloads its own voice weights the first time a line is spoken. DisTorch unloads the text encoder, VAE, and audio encoder before the 14B sample so a 16 GB card can run the chunk.

## Run it locally

Start ComfyUI first. In a second terminal, install the proxy and leave it running. It serves Comfy API v2 on port 8189 in front of port 8188:

```
pip install comfy-api-proxy
comfy-api-proxy
```

In a third terminal, from this repo:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app/server.py
```

On macOS or Linux the venv activate line is `source .venv/bin/activate`.

Open http://127.0.0.1:8765 . Paste up to 20 words and pick a voice. Emma, Alice, Isabella, and Lily are the women. Daniel, George, Lewis, and Fable are the men. Make the presenter draws a 768 still with Flux 2 Klein 9B text to image (`flux-2-klein-9b-fp8.safetensors`, `qwen_3_8b_fp8mixed.safetensors`, `flux2-vae.safetensors`). That graph is four steps at CFG 1 and loads no LoRA. An imported background is a Flux 2 reference image, and a portrait plus a background are the two reference images. Neither graph loads a LoRA. The look lists set age, hair colour, hair style, eye colour, glasses, and facial hair. Age is a number from 18 to 90. Hair styles switch with the person: women get bob, waves, long, curls, tied back, a low bun, and a fringe; men get a crop, fade, side part, quiff, short curls, tied back, and a buzz cut. Clothes switch with the person: women get a suit, a blouse under a jacket, a fine knit, a dress, a shirt, a long coat, a blazer, and a turtleneck; men get a suit, an open-collar shirt, a knit, a blazer, an overcoat, a polo, a rollneck, and a waistcoat. Generate background draws an empty studio with the same Flux 2 graph and no LoRA. The background prompt box is sent with that draw, and an empty box uses the selected set. That picture is the room reference. Animate background is a button: when it is on, the take keeps the presenter seated and moves the room behind them. A topic such as "news in ukraine war today" is searched through the public Google News RSS feed, then `hermes3:8b` in local Ollama writes one spoken line of 12 to 20 words about that topic. If the last day has no match, the search widens to the week and then to the latest headlines. Writing the line does not start a take. My line is the typed sentence. From a topic fills that same box. You can also choose your own portrait. Photo keeps that picture. Night studio, Warm studio, News desk, and Soft grey cut the person out with the open-weight u2net human model and place them on a drawn set. The first studio preview downloads that cutout model. The page posts the API graph with `comfy-sdk`:

```python
client = Comfy()  # COMFY_BASE_URL=http://127.0.0.1:8189, no API key
workflow = client.workflows.from_file("workflow/podcast_short.api.json")
workflow.set_input("7", "image", client.assets.from_file(portrait))
workflow.set_input("25", "text", script)
workflow.set_input("24", "speaker_name", voice)
job = client.submit(workflow)
```

`app/server.py` sets `COMFY_BASE_URL` to `http://127.0.0.1:8189` when that variable is empty. Point the SDK at the proxy, not at port 8188.

The video model list has five open-weight choices. LTX 2.5 Distilled Q3 loads `LTX-2.5-Distilled-Q3_K_M.gguf` through `workflow/podcast_ltx.api.json`. That is the 12 GB GGUF, and it is the default. LTX 2.5 full loads `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` and `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` through `workflow/podcast_ltx_full.api.json` for a larger card. The Q3 text encoder is `gemma412bWithProjLtx25_v10.safetensors` on the GPU, with the LTX 2.5 video and audio VAEs. Comfy unloads that encoder before the video sample. Wan 2.2 speech uses the fp8 model and the LightX2V 4-step LoRA in `workflow/podcast_short.api.json`. Wan 2.2 full uses `wan2.2_s2v_14B_bf16.safetensors` in `workflow/podcast_wan_full.api.json`, 20 steps at CFG 6, with no LoRA. Node 7 is the portrait in every graph. LTX and Wan use node 25 for the script and node 24 for the Kokoro voice. MiniMax H3 uses `workflow/podcast_minimax.api.json`: local image to video, 768 square, 124 frames, the 8-step turbo LoRA, and the spoken line inside the prompt. Its soundtrack is the model's own audio. The diffusion file is `minimax_h3_fl2va_pruned_int8_convrot.safetensors`.

The finished file is written under `outputs/` and played on the page. From there, YouTube can receive the file through the YouTube Data API with your own Google login. The redirect to register on that client is `http://127.0.0.1:8765/api/publish/youtube/callback`. The client id and secret stay in `.secrets/` on this PC. Rumble and Spotify have no public upload API for a personal channel, so those buttons open Rumble Studio and Spotify for Creators. Show the file opens the output folder so you can drop the mp4 onto those pages. A new YouTube upload is private until you change it. ComfyUI also saves a copy under its own `output/video/` folder with the prefix `Podcast-Video-Maker-Workflow`.

## Competition notes

This repo is the Open Weights Only entry for [Comfy's Open Source Higgsfield challenge](https://comfy.org/open-source-higgsfield/). Signup opened 15 October 2026. Entries close 30 October 2026 at 09:00 PT. The form is https://form.typeform.com/to/V1dSQrkS.

To enter: record a demo of two minutes or less, post it with `#OpenSourceHiggsfield`, and send the form with this repo's link. The demo, the post, and the form are yours to send.

License: MIT.
