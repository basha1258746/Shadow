# Training SHADOW

Three ways to train him, from instant to real deep learning. All of
them work with the hardware he lives on (8 GB laptop).

---

## 1. Voice lessons — instant, no GPU

Teach him a correction or a fact and he honors it in **every** reply:

```
"SHADOW, learn that I prefer short answers."
"SHADOW, learn that my favourite subject is fluid mechanics."
"my lessons"            -> review everything he has been taught
"forget lesson water"   -> drop lessons matching a word
```

Lessons live in `memory.json`, are injected into his system prompt on
every request (newest last, max 50), and survive restarts.

## 2. Persona baking — the custom `shadow` model

His personality is baked into a custom Ollama model via the repo's
`Modelfile` (base: `qwen3:1.7b`). He is SHADOW before a single line of
Python runs — even a bare `ollama run shadow "Who are you?"` answers
in butler.

To change his baked personality:

```bash
# edit Modelfile (SYSTEM block)
ollama create shadow -f Modelfile
```

…then restart him. Disk cost: zero extra (Ollama reuses the base
layers).

## 3. Real fine-tuning — free Colab GPU, LoRA

Teach him **style from his own conversations**:

1. Export his real chats (gitignored, they are private):
   ```bash
   python training/export_chats.py
   # -> chat_log_export.jsonl
   ```
2. Open `training/finetune_colab.ipynb` in
   [Google Colab](https://colab.research.google.com) (free T4 GPU),
   run the cells, upload the two JSONL files when asked.
3. ~20-40 minutes later: download `shadow-lora.zip` (a few MB).
4. Unzip into `training/`, then on the laptop:
   ```bash
   python training/import_lora.py
   # -> Ollama model "shadow-tuned"
   ```
5. Point him at it: `MODEL = "shadow-tuned"` in `shadow.py`, restart.

The notebook mixes real chats (3x weight) with the curated
`butler_examples.jsonl` so his voice improves without losing his
manners.

---

**Check status any time:** `shadow train`
