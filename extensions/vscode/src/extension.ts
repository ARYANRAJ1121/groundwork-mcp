import * as vscode from "vscode";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";

const JOBS_KEY = "groundwork.jobsByWorkspace";

type JobMap = Record<string, string>;

let client: Client | undefined;
let connection: Promise<Client> | undefined;
let output: vscode.OutputChannel;

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
  statusBar.text = "$(sync~spin) Groundwork: indexing";
  statusBar.show();
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
        vscode.window.setStatusBarMessage(`Groundwork indexed ${folder.name}`, 5000);
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
    void vscode.window.showErrorMessage(`Groundwork could not index ${folder.name}: ${message}`);
  } finally {
    statusBar.dispose();
  }
}

async function indexWorkspace(context: vscode.ExtensionContext, force = false): Promise<void> {
  const folders = vscode.workspace.workspaceFolders ?? [];
  if (folders.length === 0) {
    void vscode.window.showInformationMessage("Open a workspace folder to index it with Groundwork.");
    return;
  }
  const jobs = context.workspaceState.get<JobMap>(JOBS_KEY, {});
  for (const folder of folders) await indexFolder(context, folder, jobs, force);
}

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  output = vscode.window.createOutputChannel("Groundwork MCP");
  context.subscriptions.push(output);
  context.subscriptions.push(vscode.commands.registerCommand("groundwork.indexWorkspace", () => indexWorkspace(context, true)));

  const autoIndex = vscode.workspace.getConfiguration("groundwork").get<boolean>("autoIndex", true);
  if (autoIndex && vscode.workspace.workspaceFolders?.length) {
    void indexWorkspace(context);
  }
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
