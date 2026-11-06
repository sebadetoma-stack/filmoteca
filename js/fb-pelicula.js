// Favoritas y vistas de las páginas de película (Firebase).
// Lo carga el script de cada página solo si el visitante ya inició sesión alguna vez.
// El id de la película llega en window.__TCONST.
const { initializeApp } = await import('https://www.gstatic.com/firebasejs/10.7.1/firebase-app.js');
const { getAuth, onAuthStateChanged } = await import('https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js');
const { getFirestore, doc, getDoc, setDoc, deleteDoc, serverTimestamp } = await import('https://www.gstatic.com/firebasejs/10.7.1/firebase-firestore.js');

const firebaseConfig = {
  apiKey: "AIzaSyBh2sTmHwED1VtlvIqMOy1wFcW8CO_NZNg",
  authDomain: "filmoteca-clasica.firebaseapp.com",
  projectId: "filmoteca-clasica",
  storageBucket: "filmoteca-clasica.firebasestorage.app",
  messagingSenderId: "347321323128",
  appId: "1:347321323128:web:0dc5899523d9a8cffb678d"
};

const TCONST = window.__TCONST;
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);

let uid = null;
let esFav = false;
let esVista = false;

onAuthStateChanged(auth, async (user) => {
  if (!user) return;
  uid = user.uid;
  document.getElementById('user-actions').style.display = 'flex';

  // Cargar estado
  const [favDoc, vistaDoc] = await Promise.all([
    getDoc(doc(db, 'usuarios', uid, 'favoritos', TCONST)),
    getDoc(doc(db, 'usuarios', uid, 'vistos', TCONST))
  ]);
  esFav = favDoc.exists();
  esVista = vistaDoc.exists();
  actualizarBotones();
});

function actualizarBotones() {
  const btnFav = document.getElementById('btn-fav');
  const btnVista = document.getElementById('btn-vista');
  btnFav.textContent = esFav ? '❤️ En favoritos' : '🤍 Favorita';
  btnFav.classList.toggle('activo', esFav);
  btnVista.textContent = esVista ? '✅ Vista' : '⬜ Marcar como vista';
  btnVista.classList.toggle('activo', esVista);
}

window.toggleFav = async function() {
  if (!uid) return;
  const ref = doc(db, 'usuarios', uid, 'favoritos', TCONST);
  if (esFav) { await deleteDoc(ref); esFav = false; }
  else { await setDoc(ref, { tconst: TCONST, fecha: serverTimestamp() }); esFav = true; }
  actualizarBotones();
};

window.toggleVista = async function() {
  if (!uid) return;
  const ref = doc(db, 'usuarios', uid, 'vistos', TCONST);
  if (esVista) { await deleteDoc(ref); esVista = false; }
  else { await setDoc(ref, { tconst: TCONST, fecha: serverTimestamp() }); esVista = true; }
  actualizarBotones();
};
