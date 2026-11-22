"""v118: quadro "Especialidades" do admin -- quantos médicos há em cada especialidade e quantos são homens/mulheres.

O sistema não pergunta o gênero no cadastro; por isso ele é DEDUZIDO pelo primeiro nome (regra simples para nomes
brasileiros) e o admin pode corrigir qualquer caso na tela (grava em `medicos.genero`, migration_genero_medico.sql).
O que não dá para deduzir fica como "Não identificado" e nunca é chutado."""
import re
import unicodedata

_F_SEM_A = {"beatriz", "raquel", "isabel", "ingrid", "carmen", "miriam", "liz", "nicole", "aline", "adriane", "cristiane",
            "daniele", "michele", "simone", "viviane", "luciane", "josiane", "fabiane", "eliane", "mariane", "rosane",
            "giselle", "isabelle", "danielle", "gabrielle", "mirele", "rachel", "ester", "esther", "ruth", "lais",
            "thais", "iris", "elis", "marines", "denise", "elaine", "karine", "cristine", "caroline", "carolinne",
            "jaqueline", "jacqueline", "evelyn", "evelin", "kelly", "keli", "mary", "cintia", "alice", "bruna",
            "ariane", "adrienne", "christiane", "lilian", "lillian", "liliane", "juliane", "vanessa", "stephanie",
            "stefanie", "priscila"}
_M_COM_A = {"luca", "joshua", "jonata", "nikita", "bira"}
_M_SEM_A = {"andre", "felipe", "jose", "jaime", "rene", "denis", "wilmar", "vitor", "guilherme", "henrique", "eduardo",
            "leandre", "alexandre", "wesley", "wellington", "ney", "jorge", "luiz", "luis", "marcos", "marco", "paulo",
            "pedro", "rafael", "ricardo", "roberto", "rodrigo", "sergio", "thiago", "tiago", "bruno", "carlos", "daniel",
            "diego", "fabio", "fernando", "gabriel", "gustavo", "joao", "leonardo", "lucio", "marcelo", "mauricio",
            "miguel", "nelson", "renato", "samuel", "saulo", "victor", "vinicius", "wagner"}
# 'e'/'i' finais costumam ser femininos em -iane/-ane/-ele/-ine; deixamos a lista acima e os sufixos abaixo
_SUFIXOS_F = ("iane", "eane", "ielle", "elle", "ine", "lene", "ene")
_TRATAMENTO = re.compile(r"^(dr\.?|dra\.?|dr\(a\)\.?|doutor|doutora|prof\.?|profa\.?|profª\.?)\s+", re.I)


def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")


def deduzir_genero(nome: str) -> str | None:
    """'M', 'F' ou None (não identificado)."""
    bruto = (nome or "").strip()
    m = re.match(r"^(dra\.?|doutora)\b", _norm(bruto))
    if m:
        return "F"
    if re.match(r"^(dr\.?|doutor)\b", _norm(bruto)):
        return "M"
    limpo = _TRATAMENTO.sub("", _norm(bruto)).strip()
    primeiro = re.sub(r"[^a-z]", "", limpo.split(" ")[0]) if limpo else ""
    if not primeiro:
        return None
    if primeiro in _F_SEM_A:
        return "F"
    if primeiro in _M_COM_A or primeiro in _M_SEM_A:
        return "M"
    if primeiro.endswith("a"):
        return "F"
    if primeiro.endswith(_SUFIXOS_F):
        return "F"
    if primeiro[-1] in "orslnmzdktuhyx" or primeiro.endswith(("io", "eu", "ao")):
        return "M"
    return None


def _rotulo_especialidade(valor: str | None) -> str:
    v = re.sub(r"\s+", " ", (valor or "").strip())
    return v[:1].upper() + v[1:] if v else "Não informada"


def resumo(medicos: list[dict]) -> dict:
    """Recebe médicos (ativos) e devolve {"total", "genero": {"F","M","?"}, "especialidades": [...]}; cada especialidade traz
    contagem por gênero e a lista de médicos. Especialidades que só diferem em maiúsculas/acentos são juntadas."""
    grupos: dict[str, dict] = {}
    tot = {"F": 0, "M": 0, "?": 0}
    for m in medicos:
        g = m.get("genero") if m.get("genero") in ("M", "F") else None
        origem = "informado" if g else "deduzido"
        if not g:
            g = deduzir_genero(m.get("nome"))
        chave_g = g or "?"
        tot[chave_g] += 1
        rot = _rotulo_especialidade(m.get("especialidade"))
        chave = _norm(rot)
        gr = grupos.setdefault(chave, {"nome": rot, "F": 0, "M": 0, "?": 0, "medicos": []})
        gr[chave_g] += 1
        gr["medicos"].append({"id": m["id"], "nome": m.get("nome"), "genero": chave_g, "origem": origem})
    lista = sorted(grupos.values(), key=lambda x: (x["nome"] == "Não informada", -len(x["medicos"]), x["nome"]))
    for gr in lista:
        gr["total"] = len(gr["medicos"])
        gr["medicos"].sort(key=lambda x: _norm(x["nome"] or ""))
    return {"total": len(medicos), "genero": tot, "especialidades": lista}
