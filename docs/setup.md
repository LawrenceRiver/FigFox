# Setup

## API runner

Use Python 3.12 and Node 20 or later on macOS or Linux. From the repository root, install the dependencies and rendering browser.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm ci
npx playwright install chromium
```

Set `OPENAI_API_KEY` in the shell that will start FigFox. The runner reads environment variables from that process. Review the models and budget in `configs/factual.json`, then follow the [quick start](../README.md#quick-start). Its `--no-sam` command works without a segmentation service. For reconstruction inside an assistant, see [Skill setup](skill.md).

## Optional SAM3

SAM3 can extract image regions for reuse in the SVG. Request access to [Meta’s official SAM3 model on Hugging Face](https://huggingface.co/facebook/sam3) and obtain the weights under the access conditions and license on the model card. FigFox distributes neither the weights nor a mirror.

Start a compatible local SAM3 service. FigFox uses `POST /v1/segment/proposals` at `http://127.0.0.1:18080`. Check the service before running without `--no-sam`.

```bash
curl http://127.0.0.1:18080/health
```

For an existing browser installation or a vector-runtime override, see [runtime configuration](runtime-setup.md).
