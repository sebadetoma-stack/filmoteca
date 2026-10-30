/* Filmoteca Clásica - carga central de anuncios (Google AdSense).
 * Se sirve desde la raíz del sitio: /anuncios.js
 * Mientras PUB_ID sea el placeholder, no carga nada y los espacios se eliminan.
 */
(function () {
  'use strict';

  // 1) Completar con el ID de editor de AdSense (formato ca-pub-1234567890123456)
  var PUB_ID = 'ca-pub-XXXXXXXXXXXXXXXX';

  // 2) Completar con el ID de cada bloque de anuncios creado en AdSense.
  //    Un slot sin ID se elimina de la página sin dejar hueco.
  var SLOTS = {
    catalogo_top: '',
    catalogo_fin: '',
    pelicula_1:   '',
    pelicula_2:   '',
    blog_medio:   '',
    blog_fin:     '',
    blog_indice:  ''
  };

  if (!/^ca-pub-\d{10,}$/.test(PUB_ID)) {
    document.addEventListener('DOMContentLoaded', function () {
      var els = document.querySelectorAll('.ad-slot');
      for (var i = 0; i < els.length; i++) els[i].remove();
    });
    return;
  }

  var css = document.createElement('style');
  css.textContent =
    '.ad-slot{max-width:970px;margin:1.5rem auto;padding:0 1rem;text-align:center;min-height:100px}' +
    '.ad-slot::before{content:"Publicidad";display:block;font-size:10px;letter-spacing:.1em;' +
    'text-transform:uppercase;color:var(--text-faint,#9a8a70);margin-bottom:4px}' +
    '.ad-slot:has(ins[data-ad-status="unfilled"]){display:none}';
  document.head.appendChild(css);

  var s = document.createElement('script');
  s.async = true;
  s.crossOrigin = 'anonymous';
  s.src = 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=' + PUB_ID;
  document.head.appendChild(s);

  function init() {
    // Anuncio a mitad de artículo (solo posts largos): después del 4.º párrafo
    var body = document.querySelector('.article-body');
    if (body) {
      var ps = body.querySelectorAll(':scope > p');
      if (ps.length >= 8) {
        var mid = document.createElement('div');
        mid.className = 'ad-slot';
        mid.setAttribute('data-slot', 'blog_medio');
        ps[3].after(mid);
      }
    }

    var els = document.querySelectorAll('.ad-slot');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      var id = SLOTS[el.getAttribute('data-slot')];
      if (!id) { el.remove(); continue; }
      var ins = document.createElement('ins');
      ins.className = 'adsbygoogle';
      ins.style.display = 'block';
      ins.setAttribute('data-ad-client', PUB_ID);
      ins.setAttribute('data-ad-slot', id);
      ins.setAttribute('data-ad-format', 'auto');
      ins.setAttribute('data-full-width-responsive', 'true');
      el.appendChild(ins);
      try { (window.adsbygoogle = window.adsbygoogle || []).push({}); } catch (e) {}
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
