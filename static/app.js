// ==========================================================================
// CONSTANTES & ESTADOS GLOBAIS
// ==========================================================================
const API_URL = ""; // Relativo ao servidor local

let currentTab = "dashboard";
let dbCurrentPage = 1;
const dbPageSize = 25;
let dbTotalLeads = 0;
let dbSearchQuery = "";
let processedFilesCount = 0;
let totalDuplicatesBlocked = 0;
let resultCardHideTimeout = null;

// Arquivos selecionados
let selectedProcessFile = null;
let selectedHistoryFile = null;
let lastProcessedFileId = null;

// Debounce timer para busca
let searchDebounceTimeout = null;

// Detalhes da aba (título e descrição)
const TAB_DETAILS = {
    dashboard: {
        title: "Dashboard",
        desc: "Visão geral do seu banco e estatísticas de leads"
    },
    processar: {
        title: "Filtrar Planilha de Leads",
        desc: "Compare planilhas de leads novos contra o banco e elimine duplicatas"
    },
    historico: {
        title: "Importação de Leads Antigos (Histórico)",
        desc: "Alimente a sua base de dados com leads que já foram enviados"
    },
    database: {
        title: "Banco de Leads Cadastrados",
        desc: "Busque, visualize e gerencie todos os leads da base"
    }
};

// ==========================================================================
// INICIALIZAÇÃO
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    initDragAndDrop();
    initDatabaseView();
    initActionButtons();
    
    // Carregar dados iniciais
    updateGlobalStats();
    loadLeadsTable();
});

// ==========================================================================
// SISTEMA DE NOTIFICAÇÕES (TOAST)
// ==========================================================================
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    
    let icon = "info";
    if (type === "success") icon = "check_circle";
    if (type === "error") icon = "error";
    
    toast.innerHTML = `
        <span class="material-icons-round toast-icon">${icon}</span>
        <span>${message}</span>
    `;
    
    container.appendChild(toast);
    
    // Remover após 4 segundos
    setTimeout(() => {
        toast.style.animation = "slideIn 0.3s reverse forwards";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ==========================================================================
// CONTROLADOR DE ABAS (TABS)
// ==========================================================================
function initTabs() {
    const menuItems = document.querySelectorAll(".menu-item");
    const tabContents = document.querySelectorAll(".tab-content");
    const pageTitle = document.getElementById("page-title");
    const pageDesc = document.getElementById("page-description");

    menuItems.forEach(item => {
        item.addEventListener("click", () => {
            const targetTab = item.getAttribute("data-tab");
            
            // Alterar estado ativo nos botões do menu
            menuItems.forEach(btn => btn.classList.remove("active"));
            item.classList.add("active");
            
            // Alterar estado ativo nos wrappers de seção
            tabContents.forEach(content => content.classList.remove("active"));
            document.getElementById(`tab-${targetTab}`).classList.add("active");
            
            // Atualizar cabeçalho da página
            pageTitle.textContent = TAB_DETAILS[targetTab].title;
            pageDesc.textContent = TAB_DETAILS[targetTab].desc;
            
            currentTab = targetTab;
            
            // Ações específicas ao abrir certas abas
            if (targetTab === "database") {
                dbCurrentPage = 1;
                loadLeadsTable();
            } else if (targetTab === "dashboard") {
                updateGlobalStats();
            }
        });
    });
}

// ==========================================================================
// DRAG AND DROP & SELEÇÃO DE ARQUIVOS
// ==========================================================================
function initDragAndDrop() {
    // 1. Configurar Drag and Drop para aba de Processamento
    setupDropZone(
        "drop-zone-process", 
        "file-input-process", 
        "file-name-process", 
        "btn-process-leads",
        (file) => {
            selectedProcessFile = file;
        }
    );

    // 2. Configurar Drag and Drop para aba de Histórico
    setupDropZone(
        "drop-zone-history", 
        "file-input-history", 
        "file-name-history", 
        "btn-import-history",
        (file) => {
            selectedHistoryFile = file;
        }
    );
}

function setupDropZone(zoneId, inputId, labelId, btnId, onFileSelect) {
    const dropZone = document.getElementById(zoneId);
    const fileInput = document.getElementById(inputId);
    const fileLabel = document.getElementById(labelId);
    const actionBtn = document.getElementById(btnId);

    // Abrir seletor de arquivos ao clicar na área
    dropZone.addEventListener("click", () => fileInput.click());

    // Highlight no drag over
    ["dragenter", "dragover"].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.add("active");
        }, false);
    });

    ["dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove("active");
        }, false);
    });

    // Tratar soltura do arquivo
    dropZone.addEventListener("drop", (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            handleSelectedFile(files[0], fileLabel, actionBtn, onFileSelect);
        }
    });

    // Tratar seleção via buscador
    fileInput.addEventListener("change", (e) => {
        if (fileInput.files.length > 0) {
            handleSelectedFile(fileInput.files[0], fileLabel, actionBtn, onFileSelect);
        }
    });
}

function handleSelectedFile(file, labelElem, btnElem, onFileSelect) {
    const ext = file.name.split(".").pop().toLowerCase();
    const validExtensions = ["xlsx", "xls", "csv"];
    
    if (!validExtensions.includes(ext)) {
        showToast("Arquivo inválido! Selecione apenas planilhas Excel (.xlsx, .xls) ou CSV.", "error");
        labelElem.textContent = "Nenhum arquivo selecionado";
        btnElem.disabled = true;
        onFileSelect(null);
        return;
    }
    
    // Salvar estado do arquivo
    onFileSelect(file);
    
    // Atualizar UI
    labelElem.textContent = `${file.name} (${formatBytes(file.size)})`;
    btnElem.disabled = false;
    showToast(`Arquivo "${file.name}" carregado com sucesso!`, "success");
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// ==========================================================================
// BANCO DE DADOS - TABELA & BUSCA & PAGINAÇÃO
// ==========================================================================
function initDatabaseView() {
    const searchInput = document.getElementById("db-search-input");
    const prevBtn = document.getElementById("btn-prev-page");
    const nextBtn = document.getElementById("btn-next-page");

    // Input de busca
    searchInput.addEventListener("input", (e) => {
        dbSearchQuery = e.target.value;
        dbCurrentPage = 1; // Voltar pra primeira página
        
        // Debounce de 400ms para evitar requisições excessivas
        clearTimeout(searchDebounceTimeout);
        searchDebounceTimeout = setTimeout(() => {
            loadLeadsTable();
        }, 400);
    });

    // Paginação
    prevBtn.addEventListener("click", () => {
        if (dbCurrentPage > 1) {
            dbCurrentPage--;
            loadLeadsTable();
        }
    });

    nextBtn.addEventListener("click", () => {
        const maxPage = Math.ceil(dbTotalLeads / dbPageSize);
        if (dbCurrentPage < maxPage) {
            dbCurrentPage++;
            loadLeadsTable();
        }
    });
}

async function loadLeadsTable() {
    const tableBody = document.getElementById("leads-table-body");
    const prevBtn = document.getElementById("btn-prev-page");
    const nextBtn = document.getElementById("btn-next-page");
    const pagInfo = document.getElementById("pagination-info");

    tableBody.innerHTML = `<tr><td colspan="5" class="empty-table">Carregando leads...</td></tr>`;

    try {
        const res = await fetch(`/api/leads?page=${dbCurrentPage}&page_size=${dbPageSize}&search=${encodeURIComponent(dbSearchQuery)}`);
        if (!res.ok) throw new Error("Erro ao buscar dados.");
        
        const data = await res.json();
        const leads = data.leads;
        dbTotalLeads = data.total;

        if (leads.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="5" class="empty-table">Nenhum lead cadastrado ou encontrado.</td></tr>`;
            pagInfo.textContent = "Mostrando 0 de 0 leads";
            prevBtn.disabled = true;
            nextBtn.disabled = true;
            return;
        }

        // Montar linhas da tabela
        tableBody.innerHTML = "";
        leads.forEach(lead => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>#${lead.id}</strong></td>
                <td>${escapeHtml(lead.name)}</td>
                <td>${lead.email ? escapeHtml(lead.email) : `<span class="text-muted">-</span>`}</td>
                <td>${lead.phone ? escapeHtml(lead.phone) : `<span class="text-muted">-</span>`}</td>
                <td>${formatDate(lead.created_at)}</td>
            `;
            tableBody.appendChild(tr);
        });

        // Configurar UI de paginação
        const startRecord = (dbCurrentPage - 1) * dbPageSize + 1;
        const endRecord = Math.min(dbCurrentPage * dbPageSize, dbTotalLeads);
        pagInfo.textContent = `Mostrando ${startRecord}-${endRecord} de ${dbTotalLeads} leads`;

        prevBtn.disabled = dbCurrentPage === 1;
        nextBtn.disabled = endRecord >= dbTotalLeads;

    } catch (err) {
        console.error(err);
        tableBody.innerHTML = `<tr><td colspan="5" class="empty-table error-text">Falha ao obter dados do banco de dados.</td></tr>`;
        showToast("Não foi possível carregar os leads da tabela.", "error");
    }
}

// Helpers simples
function escapeHtml(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function formatDate(dateStr) {
    if (!dateStr) return "-";
    // Formato sqlite: YYYY-MM-DD HH:MM:SS
    // Vamos apenas amigabilizar
    try {
        const parts = dateStr.split(" ");
        const dateParts = parts[0].split("-");
        const timeParts = parts[1] ? parts[1].split(":") : ["00", "00"];
        
        const day = dateParts[2];
        const month = dateParts[1];
        const year = dateParts[0];
        
        return `${day}/${month}/${year} às ${timeParts[0]}:${timeParts[1]}`;
    } catch {
        return dateStr;
    }
}

// ==========================================================================
// AÇÕES DO BACKEND (BOTÕES E REQUISIÇÕES)
// ==========================================================================
function initActionButtons() {
    const btnProcess = document.getElementById("btn-process-leads");
    const btnImport = document.getElementById("btn-import-history");
    const btnDownload = document.getElementById("btn-download-filtered");
    const btnClearDb = document.getElementById("btn-clear-database");

    // 1. Enviar nova planilha para filtrar
    btnProcess.addEventListener("click", async () => {
        if (!selectedProcessFile) return;
        
        setBtnLoading(btnProcess, true, "Processando...");
        hideResultCard();

        const formData = new FormData();
        formData.append("file", selectedProcessFile);
        
        // Mapeamentos manuais (opcional)
        const colName = document.getElementById("map-name-process").value.stripOrEmpty();
        const colEmail = document.getElementById("map-email-process").value.stripOrEmpty();
        const colPhone = document.getElementById("map-phone-process").value.stripOrEmpty();
        
        if (colName) formData.append("col_name", colName);
        if (colEmail) formData.append("col_email", colEmail);
        if (colPhone) formData.append("col_phone", colPhone);

        try {
            const res = await fetch("/api/process-leads", {
                method: "POST",
                body: formData
            });

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || "Erro no processamento da planilha.");
            }

            const data = await res.json();
            
            if (data.success) {
                lastProcessedFileId = data.file_id;
                
                // Mostrar UI de Resultados
                showResultCard(data.stats);
                showToast("Planilha filtrada com sucesso!", "success");
                
                // Atualizar contadores locais do dashboard
                processedFilesCount++;
                totalDuplicatesBlocked += data.stats.duplicates_removed;
                
                // Atualizar banco
                updateGlobalStats();
            }
        } catch (err) {
            console.error(err);
            showToast(err.message, "error");
        } finally {
            setBtnLoading(btnProcess, false, "Filtrar e Limpar Planilha", "play_arrow");
        }
    });

    // 2. Enviar planilha de histórico
    btnImport.addEventListener("click", async () => {
        if (!selectedHistoryFile) return;

        setBtnLoading(btnImport, true, "Importando...");

        const formData = new FormData();
        formData.append("file", selectedHistoryFile);

        // Mapeamentos manuais (opcional)
        const colName = document.getElementById("map-name-history").value.stripOrEmpty();
        const colEmail = document.getElementById("map-email-history").value.stripOrEmpty();
        const colPhone = document.getElementById("map-phone-history").value.stripOrEmpty();
        
        if (colName) formData.append("col_name", colName);
        if (colEmail) formData.append("col_email", colEmail);
        if (colPhone) formData.append("col_phone", colPhone);

        try {
            const res = await fetch("/api/import-historical", {
                method: "POST",
                body: formData
            });

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || "Erro ao importar histórico.");
            }

            const data = await res.json();
            
            if (data.success) {
                showToast(data.message, "success");
                
                // Resetar estado de histórico
                selectedHistoryFile = null;
                document.getElementById("file-name-history").textContent = "Nenhum arquivo selecionado";
                btnImport.disabled = true;
                
                // Limpar campos de mapeamento
                document.getElementById("map-name-history").value = "";
                document.getElementById("map-email-history").value = "";
                document.getElementById("map-phone-history").value = "";
                
                // Atualizar banco de dados e stats
                updateGlobalStats();
            }
        } catch (err) {
            console.error(err);
            showToast(err.message, "error");
        } finally {
            setBtnLoading(btnImport, false, "Alimentar Banco de Dados", "publish");
        }
    });

    // 3. Baixar arquivo processado filtrado
    btnDownload.addEventListener("click", () => {
        if (!lastProcessedFileId) return;
        window.location.href = `/api/download-file/${lastProcessedFileId}`;
    });

    // 4. Limpar o banco de dados
    btnClearDb.addEventListener("click", async () => {
        const confirmClear = confirm("ATENÇÃO: Isso irá apagar PERMANENTEMENTE todos os leads cadastrados no seu banco de dados. Essa ação não pode ser desfeita.\n\nTem certeza absoluta que deseja prosseguir?");
        
        if (!confirmClear) return;

        try {
            const res = await fetch("/api/leads", {
                method: "DELETE"
            });

            if (!res.ok) throw new Error("Falha ao limpar banco de dados.");

            const data = await res.json();
            if (data.success) {
                showToast("Banco de dados completamente resetado.", "success");
                updateGlobalStats();
                dbCurrentPage = 1;
                loadLeadsTable();
            }
        } catch (err) {
            console.error(err);
            showToast("Erro ao tentar limpar o banco de dados.", "error");
        }
    });
}

// Helpers do botão de carregamento (Loading spinner/text)
function setBtnLoading(btnElem, isLoading, text, iconName = "") {
    btnElem.disabled = isLoading;
    if (isLoading) {
        btnElem.innerHTML = `<span class="material-icons-round rotating-icon">sync</span> ${text}`;
    } else {
        const iconHtml = iconName ? `<span class="material-icons-round">${iconName}</span>` : "";
        btnElem.innerHTML = `${iconHtml} ${text}`;
    }
}

// Helper String
String.prototype.stripOrEmpty = function() {
    return this.trim();
};

// Controlar visualização do painel de resultados
function showResultCard(stats) {
    if (resultCardHideTimeout) {
        clearTimeout(resultCardHideTimeout);
        resultCardHideTimeout = null;
    }
    const box = document.getElementById("result-box-process");
    
    document.getElementById("res-total").textContent = stats.total_rows;
    document.getElementById("res-new").textContent = stats.new_leads;
    document.getElementById("res-dup").textContent = stats.duplicates_removed;
    
    // Mapeamento detectado
    const mapping = stats.col_mapping || {};
    document.getElementById("res-map-name").textContent = mapping.name || "Não encontrada";
    document.getElementById("res-map-email").textContent = mapping.email || "Não encontrada";
    document.getElementById("res-map-phone").textContent = mapping.phone || "Não encontrada";

    // Atualizar texto do botão se for ZIP
    const btnDownload = document.getElementById("btn-download-filtered");
    if (stats.is_zip) {
        btnDownload.innerHTML = `<span class="material-icons-round">download</span> Baixar Leads Divididos (.zip)`;
    } else {
        btnDownload.innerHTML = `<span class="material-icons-round">download</span> Baixar Planilha Filtrada (.xlsx)`;
    }

    box.style.display = "flex";
    setTimeout(() => {
        box.classList.add("active");
    }, 50);
}

function hideResultCard() {
    const box = document.getElementById("result-box-process");
    box.classList.remove("active");
    if (resultCardHideTimeout) {
        clearTimeout(resultCardHideTimeout);
    }
    resultCardHideTimeout = setTimeout(() => {
        box.style.display = "none";
        resultCardHideTimeout = null;
    }, 400);
}

// ==========================================================================
// ESTATÍSTICAS GLOBAIS
// ==========================================================================
async function updateGlobalStats() {
    try {
        const res = await fetch("/api/stats");
        if (!res.ok) throw new Error();
        
        const data = await res.json();
        const total = data.total_leads;
        
        // Atualizar UIs
        document.getElementById("sidebar-total-leads").textContent = total;
        document.getElementById("stat-total-leads").textContent = total;
        document.getElementById("stat-files-processed").textContent = processedFilesCount;
        document.getElementById("stat-duplicates-removed").textContent = totalDuplicatesBlocked;
    } catch {
        console.warn("Falha ao obter status remoto do banco.");
    }
}
