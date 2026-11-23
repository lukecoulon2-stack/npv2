export const coursePrompt = `le docuements doit etre rendu en .md
les cours doivent etre verifier, propre, et ne pas se repeter.

crée un document en qui suis ce shema :

-- INFO SUR LE COURS :
matiere : <matiere du cours>
cours : <nom du cours>
niveau : <niveau scolaire du cours>
theme : <theme>
difficulté : "facile"-"intermerdiaire"-"difficile"
--

-- ORGANISATION :
1 : <nom de la premiere partie>
2 : <nom de la deuxieme partie>
etc
--

-- PARTIE X :
<presentation courte de la partie en question>
<cours en lui meme>
<exemple, si possible>
<conclusion>
<resumé de ce qu'il faut savoir>
--

!!!fin du shema!!!

si je ne te donne pas le niveau, demande le moi explicitement avant de commencer la creation du fichier.

je veux que mon cours ai comme sujet : `;

export async function readCourseFile(file) {
    if (!/\.md$/i.test(file.name) || file.size > 200 * 1024) {
        throw new Error("Choisissez un fichier .md de 200 Kio maximum.");
    }
    let markdown;
    try { markdown = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer()); }
    catch { throw new Error("Enregistrez le fichier Markdown en UTF-8 avant de l’importer."); }
    if (!markdown.trim()) throw new Error("Le fichier Markdown est vide.");
    if (markdown.length > 50000) throw new Error("Le cours est limité à 50 000 caractères.");
    return markdown;
}
