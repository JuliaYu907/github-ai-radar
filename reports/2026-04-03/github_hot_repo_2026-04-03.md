# GitHub 过去 24 小时最活跃 AI 仓库报告

> 生成时间: 2026-04-03 06:53 UTC
> 数据来源: GitHub Search API (14 组 AI topic 查询) + GitHub Trending
> 采集范围: 1901 个去重 AI 仓库 -> 分类: 核心 1384 / 应用 1538

---

## 榜单一: AI/LLM 核心仓库 — Top 10

> 框架 / 模型库 / 训练推理引擎 / 底层基础设施

| # | Repository | Lang | Stars | Forks | Score |
|---|-----------|------|------:|------:|------:|
| 1 | tensorflow/tensorflow | C++ | 194.4k | 75.3k | 14.53 |
| 2 | pytorch/pytorch | Python | 98.8k | 27.4k | 14.13 |
| 3 | huggingface/transformers | Python | 158.7k | 32.7k | 14.12 |
| 4 | Significant-Gravitas/AutoGPT | Python | 183.1k | 46.2k | 14.05 |
| 5 | ollama/ollama | Go | 166.9k | 15.3k | 13.80 |
| 6 | langgenius/dify | TypeScript | 135.6k | 21.1k | 13.80 |
| 7 | vllm-project/vllm | Python | 75.1k | 15.1k | 13.46 |
| 8 | infiniflow/ragflow | Python | 77.0k | 8.6k | 13.23 |
| 9 | firecrawl/firecrawl | TypeScript | 103.3k | 6.8k | 13.16 |
| 10 | ray-project/ray | Python | 41.9k | 7.4k | 13.07 |

### 逐一总结

**1. tensorflow/tensorflow** (194k Stars) — Google 的开源机器学习框架，深度学习领域的行业标杆。C++ 为核心、Python 为接口，涵盖分布式训练、推理部署全链路。75k forks 居全榜最高，反映其作为基础设施级项目被广泛二次开发。创建于 2015 年，十年来仍保持高频 push。

**2. pytorch/pytorch** (99k Stars) — Meta 的动态计算图深度学习框架，目前学术界和工业界最主流的训练框架。以 GPU 加速和 autograd 机制著称。18k open issues 表明社区需求极其旺盛，也是几乎所有 LLM 训练的首选底层框架。

**3. huggingface/transformers** (159k Stars) — 当前最核心的 AI 模型定义框架，支持文本、视觉、音频、多模态模型的推理与训练。Topics 中覆盖 DeepSeek / Gemma / GLM / Qwen 等 2026 年最新模型，是连接模型与应用的关键枢纽。

**4. Significant-Gravitas/AutoGPT** (183k Stars) — 自主 AI Agent 的先驱项目，愿景是让 AI 人人可用。支持 Claude / GPT / LLaMA 等多模型后端，覆盖 agentic-ai 和 autonomous-agents 两大核心领域。183k Stars 说明其在 Agent 概念爆发期积累了巨大影响力。

**5. ollama/ollama** (167k Stars) — 本地 LLM 运行工具的事实标准。用 Go 语言编写，一键运行 Kimi-K2.5 / GLM-5 / DeepSeek / gpt-oss / Qwen 等最新模型。不到 3 年达到 167k Stars，代表了 "AI 从云到端" 的本地化部署趋势。

**6. langgenius/dify** (136k Stars) — 面向生产环境的 Agentic 工作流开发平台。覆盖 Agent / RAG / MCP / 编排 / 低代码等全栈能力，是当前 AI 应用层最完整的开发平台之一。20 个 topics 体现了极广的功能覆盖面。

**7. vllm-project/vllm** (75k Stars) — 高吞吐、低内存的 LLM 推理服务引擎。支持 CUDA / AMD / TPU / Blackwell 等多种硬件。topics 覆盖 DeepSeek-V3 / gpt-oss / Kimi / Qwen3 等最新模型，是大规模模型部署的首选引擎。

**8. infiniflow/ragflow** (77k Stars) — 领先的开源 RAG 引擎，融合 RAG 与 Agent 能力。提供文档解析、GraphRAG、上下文检索等功能，topics 中含 context-engineering 和 deep-research，代表了 RAG 技术向深度研究方向的演进。

**9. firecrawl/firecrawl** (103k Stars) — AI 数据采集基础设施，将 Web 数据转化为 AI 可用的 Markdown 格式。定位 "Web Data API for AI"，为 AI Agent 提供干净的数据输入。103k Stars 说明 AI 时代的数据获取已成为刚需。

**10. ray-project/ray** (42k Stars) — AI 计算引擎，提供分布式运行时和一系列 AI 加速库。涵盖 LLM 推理/服务、超参数优化、强化学习等能力。是大规模 AI 训练和推理的关键分布式基础设施。

---

## 榜单二: AI 应用类仓库 — Top 20

> Agent / Chatbot / RAG 应用 / AI 工具链 / 低代码 AI 平台

| # | Repository | Lang | Stars | Forks | Score |
|---|-----------|------|------:|------:|------:|
| 1 | huggingface/transformers | Python | 158.7k | 32.7k | 14.12 |
| 2 | Significant-Gravitas/AutoGPT | Python | 183.1k | 46.2k | 14.05 |
| 3 | ollama/ollama | Go | 166.9k | 15.3k | 13.80 |
| 4 | langgenius/dify | TypeScript | 135.6k | 21.1k | 13.80 |
| 5 | langflow-ai/langflow | Python | 146.5k | 8.7k | 13.61 |
| 6 | vllm-project/vllm | Python | 75.1k | 15.1k | 13.46 |
| 7 | lobehub/lobehub | TypeScript | 74.7k | 14.9k | 13.32 |
| 8 | infiniflow/ragflow | Python | 77.0k | 8.6k | 13.23 |
| 9 | firecrawl/firecrawl | TypeScript | 103.3k | 6.8k | 13.16 |
| 10 | OpenHands/OpenHands | Python | 70.5k | 8.8k | 13.02 |
| 11 | netdata/netdata | C | 78.3k | 6.4k | 13.02 |
| 12 | open-webui/open-webui | Python | 129.8k | 18.4k | 13.00 |
| 13 | FlowiseAI/Flowise | TypeScript | 51.5k | 24.0k | 12.94 |
| 14 | f/prompts.chat | HTML | 156.8k | 20.6k | 12.85 |
| 15 | unslothai/unsloth | Python | 59.1k | 5.0k | 12.81 |
| 16 | huggingface/diffusers | Python | 33.2k | 6.9k | 12.78 |
| 17 | BerriAI/litellm | Python | 42.0k | 7.0k | 12.74 |
| 18 | CherryHQ/cherry-studio | TypeScript | 42.8k | 4.0k | 12.74 |
| 19 | alibaba/nacos | Java | 32.8k | 13.3k | 12.73 |
| 20 | milvus-io/milvus | Go | 43.6k | 3.9k | 12.72 |

### 逐一总结

**1. huggingface/transformers** — 同时出现在核心榜，因为它既是底层框架也是应用层调用的第一入口。Topics 中 deepseek / qwen / gemma 等表明它持续适配最新的应用模型。

**2. Significant-Gravitas/AutoGPT** — 自主 Agent 的标杆项目，同时横跨核心与应用。让普通用户也能构建和使用 AI Agent，支持多模型后端和自动化任务链。

**3. ollama/ollama** — 本地运行 LLM 的第一选择。面向终端用户的极简体验，一条命令即可运行最新模型，是 AI 应用本地化的关键基础设施。

**4. langgenius/dify** — 最完整的 Agentic 工作流平台。低代码/无代码即可构建 AI 应用，内置 RAG、Agent 编排、MCP 协议支持。

**5. langflow-ai/langflow** (147k Stars) — AI Agent 和工作流的可视化构建工具。基于 React Flow 的拖拽界面，支持多 Agent 系统和 ChatGPT 集成。147k Stars 位居应用层前列，是低代码 AI 开发的热门选择。

**6. vllm-project/vllm** — LLM 推理引擎，也是应用层部署的关键依赖。支持最新的 DeepSeek-V3 / Qwen3 / gpt-oss 模型推理。

**7. lobehub/lobehub** (75k Stars) — 工作与生活的 AI 协作空间。支持多 Agent 协作、知识库、MCP 协议，集成 ChatGPT / Claude / DeepSeek / Gemini 等主流模型。定位"Agent 团队"概念，将 Agent 作为工作交互的基本单位。

**8. infiniflow/ragflow** — 将 RAG 与 Agent 融合的检索增强生成引擎。提供文档解析、GraphRAG、深度研究等功能，是企业级知识问答系统的首选方案。

**9. firecrawl/firecrawl** — AI 数据采集 API。将网页转化为 AI Agent 可消费的结构化数据，是 AI 应用数据管线的关键组件。

**10. OpenHands/OpenHands** (70k Stars) — AI 驱动的开发工具。集成 ChatGPT / Claude 等模型，提供 CLI 级开发辅助。定位开发者工具链，代表 AI coding 方向的应用趋势。

**11. netdata/netdata** (78k Stars) — AI 增强的全栈可观测性平台。传统 DevOps 监控工具融入 AI/ML/MCP 能力，代表了传统基础设施向 AI 转型的方向。

**12. open-webui/open-webui** (130k Stars) — 用户友好的 AI 界面。支持 Ollama / OpenAI API，提供 RAG、WebUI、自托管能力。130k Stars 说明终端用户对易用 AI 界面有巨大需求。

**13. FlowiseAI/Flowise** (51k Stars) — 可视化构建 AI Agent 的低代码平台。基于 LangChain，支持 RAG、多 Agent 系统、工作流自动化。24k forks 表明大量团队基于它构建自己的 AI 应用。

**14. f/prompts.chat** (157k Stars) — 前身为 Awesome ChatGPT Prompts，现已演变为 Prompt 社区平台。覆盖 ChatGPT / Claude / Gemini 等多模型 prompt 工程，支持自托管和隐私保护。

**15. unslothai/unsloth** (59k Stars) — 模型微调与本地运行的 Web UI。支持 Qwen / DeepSeek / gpt-oss / Gemma 等模型的 fine-tuning，结合 RL 和 TTS 能力。是模型定制化的应用层入口。

**16. huggingface/diffusers** (33k Stars) — 扩散模型生成库，覆盖图像/视频/音频生成。支持 Stable Diffusion / Flux 等最新模型，是 AIGC 内容生成的核心工具。

**17. BerriAI/litellm** (42k Stars) — LLM API 网关/代理层。统一调用 100+ LLM API (OpenAI / Anthropic / Bedrock / Azure 等)，提供费用追踪、限流、日志。是多模型应用架构的关键中间件。

**18. CherryHQ/cherry-studio** (43k Stars) — AI 生产力工作站。集成智能对话、自主 Agent 和 300+ 助手，统一接入前沿 LLM。定位个人/团队 AI 效率工具。

**19. alibaba/nacos** (33k Stars) — 阿里巴巴的服务发现与配置管理平台，现已融入 AI 注册中心 (MCP Registry / A2A Registry) 能力。代表了传统微服务基础设施向 AI Agent 生态演进的趋势。

**20. milvus-io/milvus** (44k Stars) — 高性能云原生向量数据库。支持 FAISS / HNSW / DiskANN 等多种索引，是 RAG 和语义搜索应用的存储基础设施。

---

## 趋势洞察

### 1. Agent 是最大主题
两个榜单中至少 **12 个项目** 直接涉及 Agent (AutoGPT / Dify / Langflow / LobeHub / OpenHands / Flowise / Cherry Studio 等)。2026 年 AI 应用的主旋律已从"对话"全面转向"自主行动"。

### 2. 三层架构清晰化
| 层次 | 代表项目 | 职责 |
|------|----------|------|
| **基础层** | TensorFlow, PyTorch, Ray, vLLM | 训练、推理、分布式计算 |
| **模型层** | Transformers, Diffusers, Unsloth, Ollama | 模型定义、微调、本地部署 |
| **应用层** | Dify, Langflow, Flowise, Open WebUI, LobeHub | Agent 编排、RAG、用户交互 |

### 3. MCP 协议渗透广泛
Dify / LobeHub / RAGFlow / Netdata / Nacos / LiteLLM 等 **6 个项目** 的 topics 中含 `mcp`，说明 MCP (Model Context Protocol) 正在成为 AI 应用互联的事实标准。

### 4. 本地化与隐私成为刚需
Ollama (167k) / Open WebUI (130k) / Unsloth (59k) / Cherry Studio (43k) 的高关注度表明，用户对"本地运行 + 数据自主"有强烈需求。

### 5. 数据管线成为新焦点
Firecrawl (103k) / Milvus (44k) / RAGFlow (77k) 组成了从"数据采集 -> 向量存储 -> 检索增强"的完整 AI 数据管线，总 Stars 合计超过 220k。

### 6. Python 仍是 AI 第一语言
核心榜 10 个项目中 **7 个使用 Python**；应用榜 20 个项目中 **10 个使用 Python**。TypeScript 紧随其后 (核心 2 个, 应用 5 个)，主要用于前端 AI 界面和工作流编排。
