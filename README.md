# NeuroDaily 脑科学日报

每天自动搜集 **MEG / EEG / MRI / fMRI / 脑机接口 / 神经科学** 的真实新闻和最新论文，分 **中国 / 全球** 两栏，生成一个手机可看的网页。

- 只有一个文件 `neurodaily.py`，只用 Python 自带库，无需安装任何东西
- 内容全部来自真实来源并附原文链接：Google News（中英文正规媒体）、PubMed、bioRxiv/medRxiv、arXiv
- 自动去重：昨天出现过的，今天不再出现
- 中国/全球判断：论文看第一作者或末位（通讯）作者单位；英文新闻看标题是否提到中国；中文新闻默认归中国，标题讲国外（如马斯克、美国）的归全球

## 用法一：在自己电脑上运行（最简单）

```bash
python neurodaily.py
```
打开生成的 `docs/index.html` 即可。
想每天自动跑：Mac/Linux 用 `crontab -e` 加一行 `30 7 * * * cd /路径/neurodaily && python3 neurodaily.py`；Windows 用“任务计划程序”。

> 注意：Google News 在国内网络下可能打不开，此时新闻部分为空，论文部分（PubMed/arXiv/bioRxiv）一般正常。

## 用法二：放到 GitHub，全自动、手机随时看（推荐，免费，不用开电脑）

1. 在 GitHub 新建一个仓库，把本文件夹全部上传（包括 `.github/workflows/daily.yml`）。
2. 仓库 Settings → Pages → Source 选 `Deploy from a branch`，分支选 `main`，目录选 `/docs`。
3. Actions 页面点 NeuroDaily → Run workflow 试跑一次。之后每天北京时间 07:30 自动更新。
4. 手机浏览器打开 `https://你的用户名.github.io/仓库名/`，“添加到主屏幕”，就像一个 APP。

### 可选：每天推送到微信
1. 到 [Server酱](https://sct.ftqq.com/) 用微信登录，拿到 SendKey。
2. 仓库 Settings → Secrets and variables → Actions：
   - Secrets 里添加 `SERVERCHAN_KEY` = 你的 SendKey
   - Variables 里添加 `PAGE_URL` = 上面的网页地址
3. 以后每天早上微信会收到当日摘要和网页链接。

（可选）`NCBI_API_KEY`：PubMed 的免费 API key，不加也能用。

## 自定义
打开 `neurodaily.py` 顶部“配置区”：
- `TOPICS`：主题关键词（例如加一个 "OPM" 或 "经颅磁刺激"）
- `NEWS_EN` / `NEWS_ZH`：新闻检索词
- `NEWS_EXCLUDE`：要过滤掉的标题词（默认过滤炒股类内容）
- `PUBMED_MAX`、`ARXIV_MAX`：每天最多抓多少篇
