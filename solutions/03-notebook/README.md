# Notebook

`IDC_Notebook.ipynb` is a chat for the Imaging Data Commons in a Jupyter notebook. Questions in
plain English go to the IDC assistant (MCP `ask` tool) in `idc_explorer/assistant/`.

What is inside:
1. **Setup**: two cells to run once.
2. **Chat box**: type a question and press *Ask*.
3. **10 example questions**, already answered:
   - number of patients: one dataset, a scan type and body part, adding the patient's sex
   - exploring the datasets and their licences
   - raw images, with links that open them in the browser
   - analysis data (segmentations and AI results)
   - a download, which only runs when you run the *Download* cell
4. **🧪 SQL playground**: run your own read-only SQL through the MCP `query_index` tool,
   starting from an example.

```bash
.venv/bin/python -m jupyter lab solutions/03-notebook/IDC_Notebook.ipynb   # or open it in VS Code
```

The notebook must stay inside this repository, because it loads the assistant from
`../../idc_explorer/assistant`. Downloads land in `solutions/03-notebook/downloads/`.
