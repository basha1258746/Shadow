# Import a LoRA adapter trained on Colab into
# Ollama as a live model.
#
# You ran training/finetune_colab.ipynb on a
# free GPU, downloaded Shadow-lora.zip, and
# unzipped it here (training/Shadow-lora/).
# This script wires it into Ollama:
#
#   python training/import_lora.py
#
# Steps it performs:
#   1. Find the adapter (training/Shadow-lora/)
#   2. Get llama.cpp's converter (shallow clone)
#   3. Convert the adapter to GGUF
#   4. Export the base model to GGUF (one time)
#   5. Create the Ollama model "Shadow-tuned"
#
# Then point Shadow at it: set
# MODEL = "Shadow-tuned" in Shadow.py.

import os
import subprocess
import sys

TRAINING_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

REPO_DIR = os.path.dirname(TRAINING_DIR)

ADAPTER_DIR = os.path.join(
    TRAINING_DIR, "Shadow-lora"
)

LLAMA_CPP_DIR = os.path.join(
    TRAINING_DIR, "llama.cpp"
)

ADAPTER_GGUF = os.path.join(
    TRAINING_DIR, "Shadow-lora.gguf"
)

BASE_GGUF = os.path.join(
    TRAINING_DIR, "qwen3-1.7b-base.gguf"
)


def run(cmd, **kwargs):
    print(">", " ".join(cmd))

    return subprocess.run(cmd, **kwargs)


def step(name):
    print()
    print(f"=== {name} ===")


def main():
    step("1. Adapter check")

    if not os.path.isdir(ADAPTER_DIR):
        print(
            f"No adapter folder at {ADAPTER_DIR}."
        )
        print(
            "Run training/finetune_colab.ipynb in "
            "Colab, download Shadow-lora.zip, and "
            "unzip it into training/."
        )
        sys.exit(1)

    if not os.path.exists(os.path.join(
            ADAPTER_DIR,
            "adapter_config.json")):
        print(
            "adapter_config.json missing - is "
            "this the right folder?"
        )
        sys.exit(1)

    print("Adapter found.")

    step("2. llama.cpp converter")

    if not os.path.isdir(LLAMA_CPP_DIR):
        print("Cloning llama.cpp (shallow)...")

        run([
            "git", "clone", "--depth", "1",
            "https://github.com/ggml-org/llama.cpp",
            LLAMA_CPP_DIR,
        ])

    convert_lora = os.path.join(
        LLAMA_CPP_DIR,
        "convert_lora_to_gguf.py",
    )

    convert_hf = os.path.join(
        LLAMA_CPP_DIR,
        "convert_hf_to_gguf.py",
    )

    step("3. Adapter -> GGUF")

    if os.path.exists(ADAPTER_GGUF):
        print("Already converted, skipping.")

    else:
        result = run([
            sys.executable, convert_lora,
            ADAPTER_DIR,
            "--outfile", ADAPTER_GGUF,
        ])

        if result.returncode != 0:
            print(
                "Conversion failed. Usually a "
                "missing python package - install "
                "with: pip install gguf torch"
            )
            sys.exit(1)

    step("4. Base model -> GGUF (one time)")

    if os.path.exists(BASE_GGUF):
        print("Base GGUF already present, skipping.")

    else:
        print(
            "Downloading qwen3 1.7b base and "
            "converting (about 3-4 GB, one time)..."
        )

        result = run([
            sys.executable, convert_hf,
            "Qwen/Qwen3-1.7B",
            "--outfile", BASE_GGUF,
            "--outtype", "q8_0",
        ])

        if result.returncode != 0:
            print(
                "Base conversion failed. Check your "
                "internet and the packages above."
            )
            sys.exit(1)

    step("5. Create the Ollama model")

    modelfile_path = os.path.join(
        TRAINING_DIR, "Modelfile.tuned"
    )

    with open(
            modelfile_path, "w",
            encoding="utf-8") as f:
        f.write(
            "FROM " + BASE_GGUF + "\n"
            "ADAPTER " + ADAPTER_GGUF + "\n"
            "PARAMETER temperature 0.7\n"
            "PARAMETER num_ctx 4096\n"
        )

    result = run([
        "ollama", "create", "Shadow-tuned",
        "-f", modelfile_path,
    ])

    if result.returncode != 0:
        print("ollama create failed.")
        sys.exit(1)

    step("DONE")

    print(
        'Model "Shadow-tuned" is ready. Try it:'
    )
    print('  ollama run Shadow-tuned "Who are you?"')
    print()
    print("To make Shadow use it permanently:")
    print('  set MODEL = "Shadow-tuned" in '
          "Shadow.py, then restart him.")
    print()


if __name__ == "__main__":
    main()
