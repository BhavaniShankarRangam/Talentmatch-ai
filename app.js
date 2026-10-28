const jobs = [
  { id: "ai", title: "Senior AI Engineer", company: "Acme Technologies", mark: "A", color: "indigo", candidates: 48, shortlisted: 12, progress: 78 },
  { id: "data", title: "Data Engineer", company: "Acme Technologies", mark: "A", color: "blue", candidates: 36, shortlisted: 8, progress: 54 },
  { id: "product", title: "Product Designer", company: "Northstar Labs", mark: "N", color: "orange", candidates: 24, shortlisted: 5, progress: 62 },
  { id: "backend", title: "Backend Engineer", company: "Northstar Labs", mark: "N", color: "green", candidates: 31, shortlisted: 9, progress: 39 }
];

const candidatesByJob = {
  ai: [
    { id: "maya", name: "Maya Patel", initials: "MP", tone: "lilac", title: "Senior AI Engineer", years: 8, score: 98, skills: ["Python", "RAG", "LangGraph", "AWS"], status: "New", summary: "Senior AI Engineer with 8 years of experience building production LLM applications. Her recent work includes enterprise RAG pipelines, LangGraph agent workflows, AWS Bedrock, and vector search. Strong alignment with the role’s core requirements.", gaps: ["Kubernetes depth to validate"], evidence: [["RAG", "Strong match", "Built document retrieval pipelines with embeddings, hybrid search, reranking, and grounded answer generation."], ["LangGraph", "Strong match", "Designed stateful supervisor-worker workflows with tool calling and human-in-the-loop approvals."], ["AWS", "Strong match", "Deployed AI workloads using AWS Bedrock, Lambda, S3, ECS, and CloudWatch."], ["Python", "Strong match", "8 years of hands-on Python development across production AI services."]], coverage: "Required 100%", relevant: "8 years" },
    { id: "ethan", name: "Ethan Chen", initials: "EC", tone: "peach", title: "Machine Learning Engineer", years: 6, score: 95, skills: ["Python", "FastAPI", "AWS", "pgvector"], status: "In review", summary: "Machine Learning Engineer with 6 years of experience delivering cloud-based ML products. Demonstrates strong Python, FastAPI, AWS, and vector database experience; has relevant retrieval projects, with agent framework depth to explore.", gaps: ["LangGraph", "Kubernetes"], evidence: [["RAG", "Strong match", "Implemented a semantic search and grounded generation service using embeddings and pgvector."], ["Python", "Strong match", "Built and maintained production Python APIs and model-serving workflows."], ["AWS", "Strong match", "Operated ML workloads on AWS, including S3, Lambda, and SageMaker."], ["FastAPI", "Strong match", "Developed async FastAPI endpoints for model inference and retrieval."]], coverage: "Required 88%", relevant: "6 years" },
    { id: "olivia", name: "Olivia Rodriguez", initials: "OR", tone: "blue", title: "AI Platform Engineer", years: 7, score: 93, skills: ["Python", "RAG", "Docker", "Azure"], status: "Shortlisted", summary: "AI Platform Engineer with 7 years of experience developing scalable NLP and GenAI services. Strong RAG and containerization evidence; Azure is prominent, while AWS experience is less clearly demonstrated.", gaps: ["AWS Bedrock", "LangGraph"], evidence: [["RAG", "Strong match", "Created a production document assistant with retrieval evaluation and source citations."], ["Python", "Strong match", "7 years delivering Python services, NLP systems, and data pipelines."], ["Docker", "Strong match", "Packaged and deployed inference services with Docker and Kubernetes."], ["Cloud", "Partial match", "Production deployments are primarily on Azure; AWS experience is not clearly evidenced."]], coverage: "Required 82%", relevant: "7 years" },
    { id: "noah", name: "Noah Williams", initials: "NW", tone: "green", title: "Staff Software Engineer", years: 10, score: 91, skills: ["Python", "LLMs", "GCP", "SQL"], status: "In review", summary: "Staff Software Engineer with 10 years of experience, including recent LLM-powered search and document intelligence systems. Brings strong software fundamentals; specific RAG operations and AWS skills merit validation.", gaps: ["AWS", "LangGraph", "FastAPI"], evidence: [["LLM applications", "Strong match", "Delivered an internal knowledge assistant using LLMs, document retrieval, and source-aware responses."], ["Python", "Strong match", "10 years of backend and data engineering experience using Python."], ["Cloud", "Partial match", "Built and operated AI services on Google Cloud Platform."], ["RAG evaluation", "Partial match", "Retrieval quality was monitored; evaluation methodology is not described in detail."]], coverage: "Required 76%", relevant: "10 years" },
    { id: "ava", name: "Ava Thompson", initials: "AT", tone: "pink", title: "Generative AI Engineer", years: 5, score: 89, skills: ["LangChain", "RAG", "OpenAI", "Azure"], status: "New", summary: "Generative AI Engineer with 5 years in applied ML and recent enterprise assistant work. Relevant retrieval experience is present. Cloud alignment and production scale are areas for recruiter review.", gaps: ["AWS Bedrock", "LangGraph", "FastAPI"], evidence: [["RAG", "Strong match", "Built a retrieval-based knowledge assistant using hybrid search and metadata filtering."], ["Generative AI", "Strong match", "Developed LLM features with prompt iteration and grounded responses."], ["Python", "Partial match", "Python is listed across projects; scope and ownership are not fully detailed."], ["Cloud", "Partial match", "Deployed AI workloads to Azure; AWS experience is not identified."]], coverage: "Required 71%", relevant: "5 years" },
    { id: "liam", name: "Liam Johnson", initials: "LJ", tone: "yellow", title: "Senior Backend Engineer", years: 9, score: 87, skills: ["Python", "FastAPI", "Postgres", "Docker"], status: "In review", summary: "Senior Backend Engineer with 9 years of production services experience and a recent focus on AI integrations. Strong API and Python foundation; direct agent and vector-search experience needs confirmation.", gaps: ["RAG depth", "LangGraph", "AWS Bedrock"], evidence: [["Python", "Strong match", "9 years building and scaling Python backend applications."], ["FastAPI", "Strong match", "Led API development using FastAPI and async Python."], ["AI applications", "Partial match", "Integrated LLM APIs into an existing product; end-to-end retrieval architecture is unclear."], ["PostgreSQL", "Strong match", "Designed and operated PostgreSQL schemas for high-volume applications."]], coverage: "Required 65%", relevant: "9 years" },
    { id: "sophia", name: "Sophia Kim", initials: "SK", tone: "teal", title: "Machine Learning Scientist", years: 4, score: 84, skills: ["NLP", "Python", "Transformers", "GCP"], status: "New", summary: "Machine Learning Scientist with 4 years of NLP and model development experience. Strong foundation in language models and Python; production RAG implementation is not clearly evidenced.", gaps: ["RAG", "AWS", "FastAPI"], evidence: [["NLP", "Strong match", "Developed and evaluated language models for document understanding."], ["Python", "Strong match", "Used Python for model training, data processing, and experiment pipelines."], ["RAG", "Unverified", "Resume mentions retrieval research, but does not describe a production RAG system."], ["Cloud", "Partial match", "Model training workloads use GCP; AWS experience is not identified."]], coverage: "Required 59%", relevant: "4 years" },
    { id: "jack", name: "Jack Wilson", initials: "JW", tone: "violet", title: "Software Engineer, AI", years: 3, score: 78, skills: ["Python", "OpenAI", "React", "Node.js"], status: "New", summary: "Software Engineer with 3 years of experience and early hands-on work with LLM-powered product features. Potential for growth; senior-level and cloud requirements are not yet demonstrated.", gaps: ["RAG", "LangGraph", "AWS", "Experience"], evidence: [["Python", "Strong match", "Built product backend features and automation using Python."], ["LLM applications", "Partial match", "Developed a prototype using a hosted LLM API; production architecture is not described."], ["RAG", "Unverified", "Resume does not provide evidence of retrieval-augmented generation implementation."], ["Experience", "Partial match", "3 years of experience compared with the role’s senior-level expectations."]], coverage: "Required 41%", relevant: "3 years" }
  ],
  data: [
    { id: "maya", name: "Maya Patel", initials: "MP", tone: "lilac", title: "Senior Data Engineer", years: 8, score: 96, skills: ["Python", "Spark", "AWS", "Airflow"], status: "New", summary: "Senior data engineer with strong cloud data platform and orchestration experience.", gaps: ["Databricks"], evidence: [["Spark", "Strong match", "Built distributed data pipelines with Spark and Python."], ["AWS", "Strong match", "Designed data workloads on S3, Glue, and EMR."]], coverage: "Required 95%", relevant: "8 years" },
    { id: "ethan", name: "Ethan Chen", initials: "EC", tone: "peach", title: "Data Platform Engineer", years: 6, score: 93, skills: ["Python", "SQL", "Databricks", "AWS"], status: "In review", summary: "Data platform engineer with Databricks, cloud, and SQL expertise.", gaps: ["Airflow"], evidence: [["Databricks", "Strong match", "Delivered lakehouse pipelines using Databricks and Delta Lake."], ["SQL", "Strong match", "Developed analytical data models and query optimizations."]], coverage: "Required 90%", relevant: "6 years" },
    { id: "olivia", name: "Olivia Rodriguez", initials: "OR", tone: "blue", title: "Analytics Engineer", years: 7, score: 90, skills: ["dbt", "SQL", "Snowflake", "Python"], status: "Shortlisted", summary: "Analytics engineer with strong warehousing and modern data transformation experience.", gaps: ["Spark", "AWS"], evidence: [["SQL", "Strong match", "Built scalable warehouse transformations and data marts."], ["Python", "Strong match", "Created data quality and ingestion tooling."]], coverage: "Required 84%", relevant: "7 years" }
  ],
  product: [
    { id: "maya", name: "Maya Patel", initials: "MP", tone: "lilac", title: "Product Designer", years: 8, score: 95, skills: ["Figma", "Research", "Prototyping", "Systems"], status: "New", summary: "Product designer experienced in enterprise workflows, research, and design systems.", gaps: ["Consumer product"], evidence: [["Figma", "Strong match", "Led design system and prototyping work across multi-team products."], ["Research", "Strong match", "Conducted user interviews and usability studies to guide product direction."]], coverage: "Required 94%", relevant: "8 years" },
    { id: "ethan", name: "Ethan Chen", initials: "EC", tone: "peach", title: "Senior UX Designer", years: 6, score: 91, skills: ["Figma", "UX Research", "Web", "Prototyping"], status: "In review", summary: "Senior UX designer with strong interaction design and user research experience.", gaps: ["Design systems"], evidence: [["Figma", "Strong match", "Created end-to-end prototypes for responsive web products."], ["Research", "Strong match", "Planned and synthesized customer research."]], coverage: "Required 87%", relevant: "6 years" }
  ],
  backend: [
    { id: "maya", name: "Maya Patel", initials: "MP", tone: "lilac", title: "Backend Engineer", years: 8, score: 94, skills: ["Python", "APIs", "Postgres", "AWS"], status: "New", summary: "Backend engineer with a strong record building scalable API services and cloud systems.", gaps: ["Go"], evidence: [["APIs", "Strong match", "Designed high-availability REST APIs and service integrations."], ["AWS", "Strong match", "Operated production services on AWS infrastructure."]], coverage: "Required 91%", relevant: "8 years" },
    { id: "ethan", name: "Ethan Chen", initials: "EC", tone: "peach", title: "Platform Engineer", years: 6, score: 89, skills: ["Go", "Kubernetes", "APIs", "Postgres"], status: "In review", summary: "Platform engineer focused on containerized services, API reliability, and backend tooling.", gaps: ["Python", "AWS"], evidence: [["APIs", "Strong match", "Implemented and maintained internal platform APIs."], ["Kubernetes", "Strong match", "Operated containerized workloads across production clusters."]], coverage: "Required 83%", relevant: "6 years" }
  ]
};

let activeJob = "ai";
let activeTab = "all";
let selectedCandidates = new Set();
let toastTimer;

const $ = (selector) => document.querySelector(selector);
const job = () => jobs.find((item) => item.id === activeJob);
const candidates = () => candidatesByJob[activeJob] || [];
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[char]));

function renderJobs() {
  $("#jobNavigation").innerHTML = jobs.map((item) => `
    <button class="job-link ${item.id === activeJob ? "selected" : ""}" data-job="${item.id}">
      <span class="job-bullet mark-${item.color}"></span><span>${escapeHtml(item.title)}</span><small>${item.candidates}</small>
    </button>`).join("");
  $("#roleCards").innerHTML = jobs.map((item) => `
    <article class="role-card ${item.id === activeJob ? "active-role" : ""}" tabindex="0" role="button" data-job="${item.id}" aria-label="View ${escapeHtml(item.title)} candidates">
      <div class="role-top">
        <span class="company-mark mark-${item.color}">${item.mark}</span>
        <span class="role-title"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.company)}</small></span>
        <button class="role-more" aria-label="More options for ${escapeHtml(item.title)}">···</button>
      </div>
      <div class="role-meta"><span>♙ ${item.candidates} candidates</span><span class="meta-separator">·</span><span>☆ ${item.shortlisted} shortlisted</span></div>
      <div class="role-progress"><div class="progress-track"><div class="progress-fill" style="width:${item.progress}%"></div></div><small>${item.progress}% complete</small></div>
      <div class="role-foot"><span>Updated 2h ago</span><strong>${Math.round(item.candidates * item.progress / 100)} reviewed</strong></div>
    </article>`).join("");
  $("#activeJobCount").textContent = String(jobs.length).padStart(2, "0");
}

function filteredCandidates() {
  const queryTerms = $("#candidateSearch").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const minScore = Number($("#scoreFilter").value);
  return candidates().filter((person) => {
    const matchesTab = activeTab !== "shortlisted" || person.status === "Shortlisted";
    const searchable = [person.name, person.title, person.skills.join(" "), person.summary, person.gaps.join(" "), person.evidence.flat().join(" ")].join(" ").toLowerCase();
    return matchesTab && person.score >= minScore && queryTerms.every((term) => searchable.includes(term));
  });
}

function renderCandidates() {
  const visible = filteredCandidates();
  $("#allCandidateCount").textContent = candidates().length;
  $("#shortlistCount").textContent = candidates().filter((person) => person.status === "Shortlisted").length;
  $("#candidateRows").innerHTML = visible.map((person) => `
    <tr class="candidate-row" data-candidate="${person.id}" tabindex="0">
      <td><input type="checkbox" class="candidate-check" data-candidate="${person.id}" aria-label="Select ${escapeHtml(person.name)}" ${selectedCandidates.has(person.id) ? "checked" : ""}></td>
      <td><div class="candidate-info"><span class="candidate-avatar tone-${person.tone}">${person.initials}</span><span><span class="candidate-name">${escapeHtml(person.name)}</span><span class="candidate-role">${escapeHtml(person.title)}</span></span></div></td>
      <td><span class="match-value">${person.score}%</span><span class="match-label">Strong match</span></td>
      <td><div class="skill-list">${person.skills.slice(0, 3).map((skill) => `<span class="skill-chip">${escapeHtml(skill)}</span>`).join("")}${person.skills.length > 3 ? `<span class="skill-chip more">+${person.skills.length - 3}</span>` : ""}</div></td>
      <td><span class="experience">${person.years} years</span></td>
      <td><span class="status status-${person.status.toLowerCase().replace(" ", "-")}">${person.status}</span></td>
      <td><button class="row-more" aria-label="More actions for ${escapeHtml(person.name)}">···</button></td>
    </tr>`).join("");
  $("#emptyState").hidden = visible.length > 0;
  $("#candidateRows").parentElement.hidden = visible.length === 0;
  $("#resultCount").textContent = `Showing ${visible.length} of ${candidates().length} candidates`;
  $("#selectAll").checked = visible.length > 0 && visible.every((person) => selectedCandidates.has(person.id));
  $("#selectAll").indeterminate = visible.some((person) => selectedCandidates.has(person.id)) && !$("#selectAll").checked;
  $("#selectionBar").hidden = selectedCandidates.size === 0;
  $("#selectedCount").textContent = selectedCandidates.size;
}

function selectJob(id) {
  if (!candidatesByJob[id]) return;
  activeJob = id;
  activeTab = "all";
  selectedCandidates.clear();
  $("#candidateSearch").value = "";
  $("#scoreFilter").value = "0";
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === "all"));
  renderJobs();
  renderCandidates();
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 2600);
}

function candidateById(id) {
  return candidates().find((person) => person.id === id);
}

function showModal(content) {
  const modal = $("#detailModal");
  modal.innerHTML = content;
  modal.hidden = false;
  $("#modalBackdrop").hidden = false;
  modal.querySelector(".modal-close").focus();
}

function closeModal() {
  $("#detailModal").hidden = true;
  $("#modalBackdrop").hidden = true;
}

function showCandidate(id) {
  const person = candidateById(id);
  if (!person) return;
  const evidence = person.evidence.map(([skill, strength, text]) => `
    <div class="evidence-row"><span class="evidence-skill">${escapeHtml(skill)}</span>
    <span class="evidence-strength ${strength === "Partial match" ? "partial" : ""}">${escapeHtml(strength)}</span>
    <span class="evidence-text">“${escapeHtml(text)}”</span></div>`).join("");
  showModal(`
    <button class="modal-close" aria-label="Close dialog">×</button>
    <div class="modal-header"><span class="candidate-avatar tone-${person.tone}">${person.initials}</span>
      <span><h2 id="modalTitle">${escapeHtml(person.name)}</h2><span class="modal-subtitle">${escapeHtml(person.title)} · ${person.years} years experience</span></span>
      <span class="modal-score"><strong>${person.score}%</strong><small>Overall match</small></span>
    </div>
    <p class="modal-summary">${escapeHtml(person.summary)}</p>
    <div class="modal-section"><h3>Match evidence · ${person.coverage || "Skills aligned"}</h3>${evidence}</div>
    <div class="modal-section"><h3>Skills to validate</h3><div class="gap-list">${person.gaps.map((gap) => `<span class="gap-chip">${escapeHtml(gap)}</span>`).join("")}</div></div>
    <div class="modal-actions"><button data-action="email" data-candidate="${person.id}">Prepare email</button><button data-action="shortlist" data-candidate="${person.id}" class="action-primary">${person.status === "Shortlisted" ? "Remove shortlist" : "Shortlist candidate"}</button></div>`);
}

function showComparison() {
  const selected = [...selectedCandidates].map(candidateById).filter(Boolean);
  if (selected.length < 2) {
    showToast("Select at least two candidates to compare.");
    return;
  }
  const cards = selected.map((person) => `
    <article class="compare-card"><div class="compare-card-head"><span class="candidate-avatar tone-${person.tone}">${person.initials}</span><strong>${escapeHtml(person.name)}</strong></div>
      <div class="compare-match">${person.score}% <small style="font:400 8px 'DM Sans'; color:#9698a1;">match</small></div>
      <div class="compare-line"><span>Experience</span><strong>${person.years} years</strong></div>
      <div class="compare-line"><span>Required skills</span><strong>${escapeHtml(person.coverage || "See evidence")}</strong></div>
      <div class="compare-line"><span>Key skills</span><strong>${escapeHtml(person.skills.slice(0, 3).join(", "))}</strong></div>
      <div class="compare-line"><span>To validate</span><strong>${escapeHtml(person.gaps[0] || "None identified")}</strong></div>
    </article>`).join("");
  showModal(`<button class="modal-close" aria-label="Close dialog">×</button><h2 id="modalTitle" style="font:700 16px Manrope;margin:2px 0 5px">Candidate comparison</h2><p class="modal-subtitle">A side-by-side view to support your review. Final decisions remain with your team.</p><div class="compare-grid">${cards}</div><div class="modal-actions"><button class="action-primary" data-action="close">Done</button></div>`);
}

function updateShortlist(ids) {
  let changed = 0;
  for (const id of ids) {
    const person = candidateById(id);
    if (!person) continue;
    person.status = person.status === "Shortlisted" ? "In review" : "Shortlisted";
    changed++;
  }
  selectedCandidates.clear();
  renderCandidates();
  closeModal();
  if (changed) showToast(changed === 1 ? "Candidate shortlist status updated." : `${changed} candidate statuses updated.`);
}

function prepareEmail(id) {
  const person = candidateById(id);
  if (!person) return;
  showToast(`Draft summary prepared for ${person.name}. Review before sharing.`);
}

$("#jobNavigation").addEventListener("click", (event) => {
  const button = event.target.closest("[data-job]");
  if (button) selectJob(button.dataset.job);
});
$("#roleCards").addEventListener("click", (event) => {
  if (event.target.closest(".role-more")) {
    event.stopPropagation();
    showToast("Job actions are available in the full workspace.");
    return;
  }
  const card = event.target.closest("[data-job]");
  if (card) selectJob(card.dataset.job);
});
$("#roleCards").addEventListener("keydown", (event) => {
  if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-job]")) {
    event.preventDefault();
    selectJob(event.target.dataset.job);
  }
});
$("#candidateSearch").addEventListener("input", renderCandidates);
$("#scoreFilter").addEventListener("change", renderCandidates);
$("#candidateTabs").addEventListener("click", (event) => {
  const tab = event.target.closest("[data-tab]");
  if (!tab) return;
  activeTab = tab.dataset.tab;
  document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("active", item === tab));
  selectedCandidates.clear();
  renderCandidates();
});
$("#candidateRows").addEventListener("click", (event) => {
  const checkbox = event.target.closest(".candidate-check");
  if (checkbox) {
    checkbox.checked ? selectedCandidates.add(checkbox.dataset.candidate) : selectedCandidates.delete(checkbox.dataset.candidate);
    renderCandidates();
    return;
  }
  const row = event.target.closest("[data-candidate]");
  if (row) showCandidate(row.dataset.candidate);
});
$("#candidateRows").addEventListener("keydown", (event) => {
  if ((event.key === "Enter" || event.key === " ") && event.target.matches(".candidate-row")) {
    event.preventDefault();
    showCandidate(event.target.dataset.candidate);
  }
});
$("#selectAll").addEventListener("change", (event) => {
  const visibleIds = filteredCandidates().map((person) => person.id);
  visibleIds.forEach((id) => event.target.checked ? selectedCandidates.add(id) : selectedCandidates.delete(id));
  renderCandidates();
});
$("#clearSelectionButton").addEventListener("click", () => {
  selectedCandidates.clear();
  renderCandidates();
});
$("#compareButton").addEventListener("click", showComparison);
$("#bulkShortlistButton").addEventListener("click", () => updateShortlist([...selectedCandidates]));
$("#modalBackdrop").addEventListener("click", closeModal);
$("#detailModal").addEventListener("click", (event) => {
  if (event.target.closest(".modal-close") || event.target.closest('[data-action="close"]')) closeModal();
  const action = event.target.closest("[data-action]");
  if (!action) return;
  if (action.dataset.action === "shortlist") updateShortlist([action.dataset.candidate]);
  if (action.dataset.action === "email") prepareEmail(action.dataset.candidate);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("#detailModal").hidden) closeModal();
});
$("#createJobButton").addEventListener("click", () => showToast("Job creation will be available when connected to your ATS."));
$("#addJobButton").addEventListener("click", () => showToast("Job creation will be available when connected to your ATS."));
$("#viewAllButton").addEventListener("click", () => showToast("You’re viewing all sample candidates for this role."));

renderJobs();
renderCandidates();
