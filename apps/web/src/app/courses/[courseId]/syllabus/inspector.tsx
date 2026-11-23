"use client";

import { useEffect, useState } from "react";
import type { DocumentChunk, SyllabusNode, SyllabusTree } from "@/lib/api-client";

export default function SyllabusInspector({ courseId }: { courseId: string }) {

  const [tree, setTree] = useState<SyllabusTree | null>(null);
  const [selectedNode, setSelectedNode] = useState<SyllabusNode | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [loadingTree, setLoadingTree] = useState(true);
  const [loadingChunks, setLoadingChunks] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);

  const [authToken, setAuthToken] = useState<string>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("auth_token") || "";
    }
    return "";
  });

  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  useEffect(() => {
    let ignore = false;
    if (!courseId) return;

    const loadTree = async () => {
      try {
        const headers: Record<string, string> = authToken
          ? { Authorization: `Bearer ${authToken}` }
          : {};
        const res = await fetch(`${apiBase}/courses/${courseId}/syllabus`, { headers });
        if (ignore) return;
        if (res.status === 401) {
          setError("Unauthorized. Please provide an authentication token.");
          setLoadingTree(false);
          return;
        }
        if (!res.ok) {
          throw new Error(`Failed to fetch syllabus tree: HTTP ${res.status}`);
        }
        const data: SyllabusTree = await res.json();
        if (ignore) return;
        setTree(data);
        setError(null);
        if (data.nodes.length > 0) {
          setSelectedNode((prev) => prev ?? data.nodes[0]);
        }
      } catch (err: unknown) {
        if (!ignore) {
          setError(err instanceof Error ? err.message : "Failed to load syllabus tree");
        }
      } finally {
        if (!ignore) {
          setLoadingTree(false);
        }
      }
    };

    loadTree();
    return () => {
      ignore = true;
    };
  }, [courseId, authToken, apiBase, refreshIndex]);

  const selectedPath = selectedNode?.path;

  useEffect(() => {
    let ignore = false;
    if (!selectedPath) {
      return;
    }

    const loadChunks = async () => {
      try {
        const headers: Record<string, string> = authToken
          ? { Authorization: `Bearer ${authToken}` }
          : {};
        const res = await fetch(
          `${apiBase}/courses/${courseId}/syllabus/chunks?path=${encodeURIComponent(selectedPath)}`,
          { headers }
        );
        if (ignore) return;
        if (!res.ok) {
          throw new Error(`Failed to fetch chunks: HTTP ${res.status}`);
        }
        const data: DocumentChunk[] = await res.json();
        if (ignore) return;
        setChunks(data);
      } catch (err: unknown) {
        if (!ignore) {
          console.error("Failed to load chunks:", err);
          setChunks([]);
        }
      } finally {
        if (!ignore) {
          setLoadingChunks(false);
        }
      }
    };

    loadChunks();
    return () => {
      ignore = true;
    };
  }, [selectedPath, courseId, authToken, apiBase]);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      alert("Only PDF files are supported.");
      return;
    }

    try {
      setUploading(true);
      const formData = new FormData();
      formData.append("file", file);

      const headers: Record<string, string> = authToken
        ? { Authorization: `Bearer ${authToken}` }
        : {};

      const res = await fetch(`${apiBase}/courses/${courseId}/documents`, {
        method: "POST",
        headers,
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Upload failed with HTTP ${res.status}`);
      }

      setRefreshIndex((prev) => prev + 1);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Document upload failed");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const handleDevLogin = async () => {
    try {
      const res = await fetch(`${apiBase}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: "dev@example.com",
          password: "devpassword123",
        }),
      });
      if (!res.ok) throw new Error("Dev login failed");
      const data = await res.json();
      localStorage.setItem("auth_token", data.access_token);
      setAuthToken(data.access_token);
      setRefreshIndex((prev) => prev + 1);
    } catch (err) {
      alert("Dev login failed: " + String(err));
    }
  };

  return (
    <div className="flex flex-col min-h-screen bg-zinc-50 text-zinc-900 font-sans">
      {/* Top Navbar */}
      <header className="flex items-center justify-between px-6 py-4 bg-white border-b border-zinc-200 shadow-xs">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">
            Phase 2
          </span>
          <h1 className="text-lg font-bold text-zinc-900">Syllabus Inspector</h1>
          <span className="text-xs text-zinc-500 font-mono">Course: {courseId}</span>
        </div>

        <div className="flex items-center gap-3">
          {!authToken ? (
            <button
              onClick={handleDevLogin}
              className="text-xs px-3 py-1.5 font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-md transition-colors"
            >
              Sign In (Dev Account)
            </button>
          ) : (
            <label className="cursor-pointer text-xs px-3 py-1.5 font-medium text-zinc-700 bg-zinc-100 hover:bg-zinc-200 border border-zinc-300 rounded-md transition-colors inline-flex items-center gap-1.5">
              <span>{uploading ? "Ingesting PDF..." : "Upload Syllabus PDF"}</span>
              <input
                type="file"
                accept=".pdf,application/pdf"
                className="hidden"
                disabled={uploading}
                onChange={handleFileUpload}
              />
            </label>
          )}
        </div>
      </header>

      {/* Main Two-Panel Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left Panel: Syllabus Tree */}
        <aside className="w-96 border-r border-zinc-200 bg-white flex flex-col shrink-0">
          <div className="p-4 border-b border-zinc-100 flex items-center justify-between">
            <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-500">
              Curriculum Hierarchy
            </h2>
            <span className="text-xs text-zinc-400 font-mono">
              {tree?.nodes ? `${tree.nodes.length} root chapters` : "0 nodes"}
            </span>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-1">
            {loadingTree ? (
              <div className="py-12 text-center text-xs text-zinc-400">Loading syllabus tree...</div>
            ) : error ? (
              <div className="p-4 text-xs text-red-600 bg-red-50 rounded border border-red-200">
                <p className="font-semibold">Error</p>
                <p className="mt-1">{error}</p>
                {!authToken && (
                  <button
                    onClick={handleDevLogin}
                    className="mt-3 text-xs underline font-medium text-red-700 block"
                  >
                    Click to sign in with seeded dev account
                  </button>
                )}
              </div>
            ) : !tree?.nodes || tree.nodes.length === 0 ? (
              <div className="py-12 text-center text-xs text-zinc-400">
                <p>No syllabus nodes found.</p>
                <p className="mt-1">Upload a PDF handout above to generate the curriculum tree.</p>
              </div>
            ) : (
              <TreeNodeList
                nodes={tree.nodes}
                selectedNode={selectedNode}
                onSelect={(node) => setSelectedNode(node)}
              />
            )}
          </div>
        </aside>

        {/* Right Panel: Scoped Chunks & Details */}
        <main className="flex-1 flex flex-col overflow-y-auto bg-zinc-50 p-6">
          {selectedNode ? (
            <div className="max-w-4xl w-full mx-auto space-y-6">
              {/* Node Summary Card */}
              <div className="bg-white p-5 rounded-lg border border-zinc-200 shadow-xs">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs px-2 py-0.5 rounded font-mono font-medium uppercase bg-zinc-100 text-zinc-700">
                        {selectedNode.node_type || `Level ${selectedNode.level}`}
                      </span>
                      <span className="text-xs text-zinc-400 font-mono">
                        ltree: {selectedNode.path}
                      </span>
                    </div>
                    <h2 className="mt-1 text-xl font-bold text-zinc-900">{selectedNode.title}</h2>
                  </div>

                  {selectedNode.page_start !== null && selectedNode.page_start !== undefined && (
                    <div className="text-right text-xs text-zinc-500 font-mono">
                      <span>Pages {selectedNode.page_start} - {selectedNode.page_end ?? selectedNode.page_start}</span>
                    </div>
                  )}
                </div>

                {selectedNode.summary && (
                  <p className="mt-3 text-sm text-zinc-600 border-t border-zinc-100 pt-3">
                    {selectedNode.summary}
                  </p>
                )}

                {selectedNode.key_formulas && selectedNode.key_formulas.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-zinc-100">
                    <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wide">
                      Key Formulas
                    </span>
                    <div className="mt-1.5 flex flex-wrap gap-2">
                      {selectedNode.key_formulas.map((formula, idx) => (
                        <code
                          key={idx}
                          className="px-2 py-1 text-xs bg-zinc-100 text-zinc-800 rounded font-mono"
                        >
                          {formula}
                        </code>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Scoped Chunks Section */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-zinc-900 uppercase tracking-wider">
                    Scoped Document Chunks
                  </h3>
                  <span className="text-xs font-mono text-zinc-500">
                    {loadingChunks ? "Fetching..." : `${chunks.length} chunks`}
                  </span>
                </div>

                {loadingChunks ? (
                  <div className="py-12 text-center text-xs text-zinc-400">Loading scoped chunks...</div>
                ) : chunks.length === 0 ? (
                  <div className="bg-white p-8 rounded-lg border border-dashed border-zinc-200 text-center text-xs text-zinc-400">
                    No document chunks found under scope path &ldquo;{selectedNode.path}&rdquo;.
                  </div>
                ) : (
                  <div className="space-y-4">
                    {chunks.map((chunk) => (
                      <div
                        key={chunk.id}
                        className="bg-white p-4 rounded-lg border border-zinc-200 shadow-xs space-y-3"
                      >
                        <div className="flex items-center justify-between text-xs text-zinc-500 font-mono">
                          <span className="bg-zinc-100 px-2 py-0.5 rounded text-zinc-700">
                            Page {chunk.page ?? "?"}
                          </span>
                          <span>{chunk.source_filename || "unknown file"}</span>
                        </div>

                        <div className="text-sm text-zinc-800 font-mono whitespace-pre-wrap leading-relaxed bg-zinc-50 p-3 rounded border border-zinc-100">
                          {chunk.markdown}
                        </div>

                        {chunk.raw_latex && chunk.raw_latex.length > 0 && (
                          <div className="pt-2 border-t border-zinc-100 flex flex-wrap items-center gap-1.5">
                            <span className="text-xs font-medium text-zinc-400">LaTeX:</span>
                            {chunk.raw_latex.map((latex, idx) => (
                              <span
                                key={idx}
                                className="text-xs px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded font-mono"
                              >
                                {latex}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-zinc-400 text-sm">
              <p>Select a node from the curriculum tree on the left.</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function TreeNodeList({
  nodes,
  selectedNode,
  onSelect,
  level = 0,
}: {
  nodes: SyllabusNode[];
  selectedNode: SyllabusNode | null;
  onSelect: (node: SyllabusNode) => void;
  level?: number;
}) {
  return (
    <ul className="space-y-1">
      {nodes.map((node) => {
        const isSelected = selectedNode?.id === node.id || selectedNode?.path === node.path;
        return (
          <li key={node.path || node.id}>
            <button
              onClick={() => onSelect(node)}
              style={{ paddingLeft: `${Math.max(8, level * 16 + 8)}px` }}
              className={`w-full text-left py-2 pr-3 rounded-md text-xs flex items-center justify-between transition-colors ${
                isSelected
                  ? "bg-indigo-50 text-indigo-900 font-semibold border-l-2 border-indigo-600"
                  : "text-zinc-700 hover:bg-zinc-100"
              }`}
            >
              <div className="flex items-center gap-2 truncate">
                <span
                  className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                    node.children && node.children.length > 0
                      ? "bg-indigo-500"
                      : "bg-zinc-300"
                  }`}
                />
                <span className="truncate">{node.title}</span>
              </div>
              {node.page_start !== null && node.page_start !== undefined && (
                <span className="text-2xs text-zinc-400 font-mono shrink-0 ml-1">
                  p.{node.page_start}
                </span>
              )}
            </button>

            {node.children && node.children.length > 0 && (
              <div className="mt-0.5">
                <TreeNodeList
                  nodes={node.children}
                  selectedNode={selectedNode}
                  onSelect={onSelect}
                  level={level + 1}
                />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
