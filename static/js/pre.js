// pre.js - roda antes de a pagina ser pintada: avisa o CSS que o JavaScript esta ativo.
// (Sem JS, o menu lateral aparece empilhado no celular em vez de escondido.)
document.documentElement.classList.add('js');
