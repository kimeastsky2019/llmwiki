# gpu-server 배포 — 210.206.73.80

Ubuntu 24.04 · NVIDIA A30 24GB · LLMWiki(규제 준수 평가) + 사내 sLLM(Ollama).

이전 서버(`../README.md`)와 다른 점은 하나다. 거기서는 A30 을 rag-api 와 나눠 써서
기본 공급자가 Grok 이었는데, 여기서는 **GPU 를 혼자 쓰므로 기본이 사내 sLLM** 이다.
소스와 규제 문서가 조직 밖으로 나가지 않는 구성이 기본값이 된다.

```
브라우저 ──80──▶ nginx (basic auth) ──▶ llmwiki 127.0.0.1:8722
                                          └─▶ ollama 127.0.0.1:11434  (Qwen3-30B-A3B Q4_K_M)
                                          └─▶ xAI Grok  (사람이 고를 때만)
```

## 처음 한 번

맥에서:

```bash
cd ~/Documents/Sloution/LLMWiki
read -rs XAI_API_KEY && export XAI_API_KEY      # 이력에 남기지 않으려면 이렇게
./deploy/gpu-server/push.sh --bootstrap
```

`push.sh` 가 프론트를 빌드해 `/tmp/up` 으로 올리고, 서버에서 `bootstrap.sh` 를 돌린다.
드라이버가 없으면 거기서 멈추고 안내가 나온다 — `sudo ubuntu-drivers install` 후 재부팅하고
같은 명령을 다시 돌리면 된다.

모델 내려받기(약 18GB)가 가장 오래 걸린다. 회선에 따라 10~40분.

## 다시 배포할 때

```bash
./deploy/gpu-server/push.sh
```

코드와 프론트만 밀어 넣고 서비스를 재시작한다. 설정·키·모델은 건드리지 않는다.

## 확인

```bash
ssh -i ~/Documents/Webpage/ETS/dhkim-key.pem ubuntu@210.206.73.80

curl -u llmwiki:<비밀번호> -s http://127.0.0.1/api/meta | head -c 300
curl -s http://127.0.0.1:11434/api/tags | head -c 300
journalctl -u llmwiki -n 50 --no-pager
nvidia-smi
```

바깥에서 80 이 열려 있으면 `http://210.206.73.80/` 로 바로 들어간다.
상위망이 80 을 막고 있으면(이전 서버가 그랬다) 터널로 본다:

```bash
ssh -i ~/Documents/Webpage/ETS/dhkim-key.pem -L 8722:127.0.0.1:8722 ubuntu@210.206.73.80
# → http://127.0.0.1:8722  (터널은 nginx 를 건너뛰므로 basic auth 없이 열린다)
```

## sLLM 을 무엇으로 돌릴지

| | Ollama | vLLM |
|---|---|---|
| 붙이는 비용 | 코드에 공급자가 이미 있다 | OpenAI 호환 공급자를 새로 써야 한다 |
| 동시 요청 | 1~2 | 수십 (연속 배칭) |
| 양자화 | GGUF Q4 로 30B 급이 24GB 에 들어간다 | AWQ/GPTQ, 14B 급이 현실적 |
| 적합 | 지금처럼 담당자 몇 명이 쓰는 내부 도구 | 평가 자동화가 대량 배치로 돌 때 |

지금은 Ollama 로 간다. Phase 2 의 결과 실측(프롬프트 배치 평가)이 들어오면
그때 vLLM 을 얹고 공급자 하나만 추가하면 된다 — `llmwiki/llm/` 에 파일 하나다.

A30 은 Ampere 라 FP8 이 없다. bf16/GGUF 로만 간다.

## 주의

* `compliance/` `knowledge/` `wiki/` 는 append-only 감사 추적이다. 재배포로 지워지지
  않게 `push.sh` 는 이 경로를 건드리지 않는다. 백업 대상이다.
* 앱에는 인증이 없다. nginx basic auth 가 유일한 방어선이라 절대 빼지 않는다.
* Ollama 는 127.0.0.1 에만 연다. 공인 IP 로 11434 가 열리면 모델이 그대로 공개된다.
