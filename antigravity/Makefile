.PHONY: deps build model run install clean allocator llama

MODEL_DIR   := $(HOME)/models
MODEL_URL   := https://huggingface.co/bartowski/google_gemma-3n-E2B-it-GGUF/resolve/main/google_gemma-3n-E2B-it-Q4_K_M.gguf
MMPROJ_URL  := https://huggingface.co/bartowski/google_gemma-3n-E2B-it-GGUF/resolve/main/mmproj-google_gemma-3n-E2B-it-f16.gguf
MODEL_PATH  := $(MODEL_DIR)/gemma-3n-e2b-it-q4_k_m.gguf
MMPROJ_PATH := $(MODEL_DIR)/gemma-3n-e2b-it-mmproj.gguf

deps:
	sudo apt update && sudo apt install -y \
		python3-pyqt6 python3-psutil build-essential \
		cgroup-tools sqlite3 cmake wget curl git lm-sensors \
		xfce4 xfce4-goodies xrdp dbus-x11 nvidia-cuda-toolkit
	pip3 install --user -r requirements.txt

build: allocator llama

allocator: allocator.c
	gcc -O2 -Wall -o allocator allocator.c

llama:
	@if [ ! -d "$(HOME)/llama.cpp" ]; then \
		git clone https://github.com/ggerganov/llama.cpp.git $(HOME)/llama.cpp; \
	fi
	cd $(HOME)/llama.cpp && cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON && \
		cmake --build build --config Release -j$$(nproc)

model:
	mkdir -p $(MODEL_DIR)
	@[ -f "$(MODEL_PATH)" ]  || wget -O $(MODEL_PATH)  $(MODEL_URL)
	@[ -f "$(MMPROJ_PATH)" ] || wget -O $(MMPROJ_PATH) $(MMPROJ_URL)

run: allocator
	sudo ./allocator 70
	bash start.sh

install:
	mkdir -p $(HOME)/.config/systemd/user
	cp systemd/*.service $(HOME)/.config/systemd/user/
	systemctl --user daemon-reload
	systemctl --user enable --now allocator.service
	systemctl --user enable --now llama-server.service
	systemctl --user enable --now nexus-agent.service
	systemctl --user enable --now nexus-sidebar.service

clean:
	rm -f allocator
	rm -f $(HOME)/.local/share/nexus/context.db
