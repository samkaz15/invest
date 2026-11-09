// Open in macOS Script Editor with the language set to JavaScript, then click Run.
const repository = "samkaz15/invest";
const reportDirectory = "docs/reports/us_policy";
const runIdPattern = /^\d{8}T\d{6}Z-[0-9a-f]{8}$/;
const documentIdPattern = /^[a-z0-9][a-z0-9_-]{0,179}$/;

function fetchText(app, url) {
    // All URLs are assembled from fixed hosts and validated path segments.
    const quotedUrl = "'" + url.replace(/'/g, "'\\''") + "'";
    try {
        return app.doShellScript(
            "/usr/bin/curl --disable --fail --silent --show-error --location " +
            "--proto '=https' --proto-redir '=https' --connect-timeout 8 --max-time 25 " +
            quotedUrl,
            { alteringLineEndings: false }
        );
    } catch (error) {
        throw new Error("GitHubから取得できませんでした。\n" + url + "\n" + error.message);
    }
}

function reportPath(runId) {
    return reportDirectory + "/" + runId + ".ja.md";
}

function findRun(app, requestedId) {
    if (requestedId && !runIdPattern.test(requestedId)) {
        throw new Error("調査IDの形式が違います。例 20261109T092316Z-d992bcf1");
    }
    const api = "https://api.github.com/repos/" + repository;
    const path = requestedId ? reportPath(requestedId) : reportDirectory;
    const history = JSON.parse(fetchText(app,
        api + "/commits?sha=main&per_page=1&path=" + encodeURIComponent(path)));
    if (!Array.isArray(history) || !history.length || !/^[0-9a-f]{40}$/.test(history[0].sha)) {
        throw new Error("指定した調査レポートがGitHubのmainに見つかりません。");
    }
    const revision = history[0].sha;
    if (requestedId) {
        return { id: requestedId, revision: revision };
    }
    const commit = JSON.parse(fetchText(app, api + "/commits/" + revision));
    const ids = commit.files
        .filter(file => file.status !== "removed" && file.filename.startsWith(reportDirectory + "/"))
        .map(file => file.filename.slice(reportDirectory.length + 1).replace(/\.ja\.md$/, ""))
        .filter(id => runIdPattern.test(id))
        .sort();
    if (!ids.length) {
        throw new Error("最新コミットで調査IDを確認できません。調査IDを指定して再実行してください。");
    }
    return { id: ids[ids.length - 1], revision: revision };
}

function run() {
    const app = Application.currentApplication();
    app.includeStandardAdditions = true;
    const response = app.displayDialog(
        "空欄で最新の調査を開きます。過去の調査は調査IDを入力してください。",
        { defaultAnswer: "", withTitle: "米国政策・経済調査" }
    );
    const report = findRun(app, response.textReturned.trim());
    const raw = "https://raw.githubusercontent.com/" + repository + "/" + report.revision + "/";
    const reportOption = "調査レポート";
    let documentIds = [];
    let translationNotice = "";
    try {
        const analysis = JSON.parse(fetchText(app, raw + "data/analysis/us_policy/" + report.id + ".json"));
        if (!Array.isArray(analysis.new_document_ids) ||
            !analysis.new_document_ids.every(id => typeof id === "string" && documentIdPattern.test(id))) {
            throw new Error("当回の文書一覧が記録されていません。");
        }
        documentIds = analysis.new_document_ids;
    } catch (error) {
        translationNotice = "当回の翻訳一覧を取得できませんでした。\n" + error.message + "\n\n";
    }
    const options = [reportOption].concat(documentIds);
    const selection = app.chooseFromList(options, {
        withTitle: "米国政策・経済調査",
        withPrompt: report.id + " の表示内容を選択",
        defaultItems: [reportOption]
    });
    if (selection === false) {
        return;
    }
    if (selection[0] === reportOption) {
        return translationNotice + fetchText(app, raw + reportPath(report.id));
    }
    if (!documentIds.includes(selection[0])) {
        throw new Error("翻訳の選択内容を確認できません。");
    }
    return fetchText(app, raw + "docs/translations/us/" + selection[0] + ".ja.md");
}
