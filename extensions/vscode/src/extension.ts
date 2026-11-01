import * as vscode from "vscode";
import { randomBytes } from "node:crypto";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";

const JOBS_KEY = "groundwork.jobsByWorkspace";
const GUIDE_URL = "https://github.com/ARYANRAJ1121/groundwork-mcp/blob/main/extensions/vscode/README.md";

type JobMap = Record<string, string>;
type DashboardStatus = { title: string; detail: string; busy: boolean };

let client: Client | undefined;
let connection: Promise<Client> | undefined;
let output: vscode.OutputChannel;
let dashboard: vscode.WebviewView | undefined;
let status: DashboardStatus = {
  title: "Ready to index",
  detail: "Open a folder and Groundwork will build its local code index.",
  busy: false,
};

function updateDashboard(next: DashboardStatus): void {
  status = next;
  void dashboard?.webview.postMessage({ type: "status", ...status });
}

function startClient(): Promise<Client> {
  if (client) return Promise.resolve(client);
  if (connection) return connection;

  connection = (async () => {
    const settings = vscode.workspace.getConfiguration("groundwork");
    const command = settings.get<string>("command", "uvx");
    const args = settings.get<string[]>("args", ["--from", "groundwork-mcp", "groundwork-mcp"]);
    const inheritedEnv = Object.fromEntries(
      Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined),
    );
    const transport = new StdioClientTransport({ command, args, env: inheritedEnv });
    const nextClient = new Client({ name: "groundwork-vscode", version: "0.1.0" });
    await nextClient.connect(transport);
    client = nextClient;
    output.appendLine(`Connected to Groundwork using ${command} ${args.join(" ")}`);
    return nextClient;
  })().catch((error: unknown) => {
    connection = undefined;
    throw error;
  });

  return connection;
}

function textResult(result: { content?: Array<{ type: string; text?: string }>; isError?: boolean }): string {
  const text = result.content?.filter((item) => item.type === "text").map((item) => item.text ?? "").join("\n") ?? "";
  if (result.isError) throw new Error(text || "Groundwork MCP tool call failed.");
  return text;
}

async function indexFolder(
  context: vscode.ExtensionContext,
  folder: vscode.WorkspaceFolder,
  jobs: JobMap,
  force = false,
): Promise<void> {
  const folderPath = folder.uri.fsPath;
  const existingJob = jobs[folderPath];
  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 10);
  statusBar.command = "groundwork.openDashboard";
  statusBar.text = "$(sync~spin) Groundwork: indexing";
  statusBar.tooltip = "Groundwork is building a local index. Click to open the Groundwork panel.";
  statusBar.show();
  updateDashboard({ title: `Indexing ${folder.name}`, detail: "Reading project files into a local code index…", busy: true });
  output.appendLine(`Indexing workspace folder: ${folderPath}`);

  try {
    const server = await startClient();
    let jobId = force ? undefined : existingJob;
    if (!jobId) {
      const response = textResult(await server.callTool({
        name: "ingest_local_path",
        arguments: { path: folderPath },
      }));
      const match = response.match(/job_id:\s*([0-9a-f-]{36})/i)
        ?? response.match(/get_ingest_status\(['"]([0-9a-f-]{36})/i);
      if (!match) {
        output.appendLine(response);
        throw new Error("Groundwork did not return an ingestion job ID.");
      }
      jobId = match[1];
      jobs[folderPath] = jobId;
      await context.workspaceState.update(JOBS_KEY, jobs);
      output.appendLine(`Started job ${jobId}`);
    }

    for (let attempt = 0; attempt < 600; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      const response = textResult(await server.callTool({
        name: "get_ingest_status",
        arguments: { job_id: jobId },
      }));
      output.appendLine(response.replace(/\n/g, " | "));
      if (/Status:\s+complete/i.test(response)) {
        const summary = response.match(/Complete!\s+([\d,]+)\s+files,\s*~?([\d,]+)\s*tokens/i);
        const detail = summary
          ? `${summary[1]} files indexed · about ${summary[2]} tokens · source stays on this machine.`
          : "Workspace indexed successfully. Source stays on this machine.";
        updateDashboard({ title: `${folder.name} is indexed`, detail, busy: false });
        statusBar.text = "$(check) Groundwork: ready";
        statusBar.tooltip = "Workspace indexed. Click to open Groundwork and see how to use the index.";
        setTimeout(() => statusBar.dispose(), 6000);
        void vscode.window.setStatusBarMessage(`Groundwork indexed ${folder.name}`, 5000);
        return;
      }
      if (/Status:\s+failed/i.test(response)) {
        delete jobs[folderPath];
        await context.workspaceState.update(JOBS_KEY, jobs);
        throw new Error(response);
      }
    }
    throw new Error(`Indexing job ${jobId} is still running; use Groundwork: Index Workspace to check again.`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`Indexing failed: ${message}`);
    updateDashboard({
      title: "Indexing needs attention",
      detail: message.includes("uvx") || message.includes("ENOENT")
        ? "Groundwork could not start. Install uv, then restart VS Code. See Setup guide for help."
        : message,
      busy: false,
    });
    statusBar.text = "$(warning) Groundwork: setup needed";
    statusBar.tooltip = "Groundwork needs attention. Click to open the dashboard.";
    setTimeout(() => statusBar.dispose(), 10000);
    void vscode.window.showErrorMessage(`Groundwork could not index ${folder.name}: ${message}`, "Open Setup Guide")
      .then((choice) => choice === "Open Setup Guide" && vscode.env.openExternal(vscode.Uri.parse(GUIDE_URL)));
  }
}

async function indexWorkspace(context: vscode.ExtensionContext, force = false): Promise<void> {
  const folders = vscode.workspace.workspaceFolders ?? [];
  if (folders.length === 0) {
    updateDashboard({ title: "Open a project folder", detail: "Choose File → Open Folder to get started with Groundwork.", busy: false });
    void vscode.window.showInformationMessage("Open a workspace folder to index it with Groundwork.");
    return;
  }
  const jobs = context.workspaceState.get<JobMap>(JOBS_KEY, {});
  for (const folder of folders) await indexFolder(context, folder, jobs, force);
}

function dashboardHtml(logoUri: string, cspSource: string): string {
  const nonce = randomBytes(16).toString("base64");
  const escapeHtml = (value: string): string => value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  })[character] ?? character);
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${cspSource}; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
  <title>Groundwork</title>
  <style>
    :root { color-scheme: light dark; }
    body { padding: 16px; color: var(--vscode-foreground); font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); line-height: 1.55; }
    .wordmark { display: block; width: 100%; height: auto; margin: 0 0 18px; }
    .tagline { color: var(--vscode-descriptionForeground); margin: 2px 0 18px; }
    .card { border: 1px solid var(--vscode-panel-border); border-radius: 6px; padding: 12px; margin: 12px 0; background: var(--vscode-sideBar-background); }
    .state { font-weight: 600; margin-bottom: 4px; }
    .detail, .muted { color: var(--vscode-descriptionForeground); }
    button { display: block; width: 100%; border: 0; border-radius: 3px; margin: 8px 0; padding: 8px 10px; cursor: pointer; color: var(--vscode-button-foreground); background: var(--vscode-button-background); text-align: center; }
    button:hover { background: var(--vscode-button-hoverBackground); }
    button.secondary { color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground); }
    button:disabled { opacity: .65; cursor: wait; }
    h2 { font-size: 13px; margin: 18px 0 4px; }
    .privacy { border-left: 2px solid var(--vscode-textLink-foreground); padding-left: 10px; }
    a { color: var(--vscode-textLink-foreground); }
    code { font-family: var(--vscode-editor-font-family); font-size: .92em; }
  </style>
</head>
<body>
  <img class="wordmark" src="${escapeHtml(logoUri)}" alt="GROUNDWORK — just one quick grep, 47 files later.">
  <p class="tagline">Give your AI assistant a searchable map of the project you’re working on.</p>
  <section class="card" aria-live="polite">
    <div class="state" id="state">${escapeHtml(status.title)}</div>
    <div class="detail" id="detail">${escapeHtml(status.detail)}</div>
  </section>
  <button id="index" ${status.busy ? "disabled" : ""}>${status.busy ? "Indexing…" : "Index this workspace"}</button>
  <button class="secondary" id="output">View indexing log</button>
  <h2>What Groundwork does</h2>
  <p>It indexes code on this computer. An AI assistant connected to Groundwork MCP can then search the index and answer with file and line citations.</p>
  <p class="privacy">Your workspace source stays on this machine in local mode. Groundwork does not send it to a hosted indexing service.</p>
  <h2>One more step: connect your AI assistant</h2>
  <p>This extension creates the index. To ask questions in Claude or another MCP-compatible assistant, connect that assistant to Groundwork MCP using the setup guide.</p>
  <button class="secondary" id="guide">Open the quick-start guide</button>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    document.getElementById('index').addEventListener('click', () => vscode.postMessage({ command: 'index' }));
    document.getElementById('output').addEventListener('click', () => vscode.postMessage({ command: 'output' }));
    document.getElementById('guide').addEventListener('click', () => vscode.postMessage({ command: 'guide' }));
    window.addEventListener('message', event => {
      const state = event.data;
      if (state.type !== 'status') return;
      document.getElementById('state').textContent = state.title;
      document.getElementById('detail').textContent = state.detail;
      const button = document.getElementById('index');
      button.disabled = state.busy;
      button.textContent = state.busy ? 'Indexing…' : 'Index this workspace';
    });
  </script>
</body>
</html>`;
}

class GroundworkDashboard implements vscode.WebviewViewProvider {
  constructor(private readonly context: vscode.ExtensionContext) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    dashboard = view;
    view.webview.options = { enableScripts: true, localResourceRoots: [this.context.extensionUri] };
    const logoUri = view.webview.asWebviewUri(vscode.Uri.joinPath(this.context.extensionUri, "media", "groundwork-banner.png"));
    view.webview.html = dashboardHtml(logoUri.toString(), view.webview.cspSource);
    view.webview.onDidReceiveMessage(async (message: { command?: string }) => {
      if (message.command === "index") await indexWorkspace(this.context, true);
      if (message.command === "output") output.show(true);
      if (message.command === "guide") await vscode.env.openExternal(vscode.Uri.parse(GUIDE_URL));
    }, undefined, this.context.subscriptions);
    view.onDidDispose(() => {
      if (dashboard === view) dashboard = undefined;
    }, undefined, this.context.subscriptions);
    void view.webview.postMessage({ type: "status", ...status });
  }
}

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  output = vscode.window.createOutputChannel("Groundwork MCP");
  context.subscriptions.push(output);
  context.subscriptions.push(vscode.window.registerWebviewViewProvider("groundwork.dashboard", new GroundworkDashboard(context)));
  context.subscriptions.push(vscode.commands.registerCommand("groundwork.indexWorkspace", () => indexWorkspace(context, true)));
  context.subscriptions.push(vscode.commands.registerCommand("groundwork.showOutput", () => output.show(true)));
  context.subscriptions.push(vscode.commands.registerCommand("groundwork.openDashboard", () => vscode.commands.executeCommand("workbench.view.extension.groundwork")));
  context.subscriptions.push(vscode.commands.registerCommand("groundwork.openGuide", () => vscode.env.openExternal(vscode.Uri.parse(GUIDE_URL))));

  const folders = vscode.workspace.workspaceFolders ?? [];
  if (!folders.length) {
    updateDashboard({ title: "Open a project folder", detail: "Choose File → Open Folder to get started with Groundwork.", busy: false });
  }
  const autoIndex = vscode.workspace.getConfiguration("groundwork").get<boolean>("autoIndex", true);
  if (autoIndex && folders.length) void indexWorkspace(context);
  context.subscriptions.push(vscode.workspace.onDidChangeWorkspaceFolders((event) => {
    if (!vscode.workspace.getConfiguration("groundwork").get<boolean>("autoIndex", true)) return;
    const jobs = context.workspaceState.get<JobMap>(JOBS_KEY, {});
    for (const folder of event.added) void indexFolder(context, folder, jobs);
  }));
}

export async function deactivate(): Promise<void> {
  if (client) await client.close();
  client = undefined;
  connection = undefined;
}
