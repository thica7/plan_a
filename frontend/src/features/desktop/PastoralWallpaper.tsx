/** Original geometric scenery, drawn locally without external assets. */
export function PastoralWallpaper() {
  return <svg className="pastoral-scenery" viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice" aria-hidden="true" shapeRendering="crispEdges">
    <path className="scenery-sky" d="M0 0H320V180H0z" />
    <path className="scenery-sun" d="M260 20h16v4h4v16h-4v4h-16v-4h-4V24h4z" />
    <g className="scenery-cloud"><path d="M20 28h8v-5h20v5h10v6h7v8H14v-8h6zM150 14h10v-5h16v5h12v6h6v7h-51v-7h7zM232 60h11v-6h20v6h11v6h7v7h-56v-7h7z" /></g>
    <path className="scenery-mountain-far" d="M0 100h18v-8h20v-9h20v-8h20v8h18v9h20v-8h18v-8h16V66h22v10h20v9h18v11h21V82h18V70h18v12h18v9h21v10h21v-8h18v87H0z" />
    <path className="scenery-mountain-near" d="M0 124h20v-8h30v-9h27v9h25v7h30v-10h24v-9h28v9h25v8h27v-12h24v-9h24v9h22v10h14v61H0z" />
    <path className="scenery-grass" d="M0 140h25v-5h42v5h40v-4h45v4h33v-6h35v6h46v-4h31v4h23v40H0z" />
    <path className="scenery-path" d="M235 145h16v8h-10v9h-12v9h-13v9h-40v-9h22v-9h18v-9h19z" />
    <g className="scenery-house"><path fill="#8d573f" d="M224 124h6v-6h6v-6h26v6h6v6h6v6h-50z" /><path fill="#f3d9a2" d="M229 130h39v24h-39z" /><path fill="#c58b58" d="M229 149h39v5h-39zM251 136h10v18h-10z" /><path fill="#6f9b9a" d="M235 135h9v9h-9z" /><path fill="#fff1cb" d="M239 135h1v9h-1zM235 139h9v1h-9z" /><path fill="#704634" d="M260 114h5v-9h-5z" /></g>
    <g className="scenery-trees" fill="#477852"><path d="M291 114h8v6h5v7h5v8h-28v-8h5v-7h5zM20 126h7v5h5v7h4v6H12v-6h4v-7h4z" /><path fill="#986840" d="M293 135h5v16h-5zM22 144h4v11h-4z" /></g>
    <g fill="#67984e"><path d="M45 153h3v3h-3zM51 156h3v3h-3zM82 167h4v2h-4zM126 150h3v3h-3zM285 169h4v2h-4zM20 174h4v2h-4zM310 153h3v3h-3z" /></g>
    <g fill="#fff1cb"><path d="M63 153h2v2h-2zM93 172h2v2h-2zM148 160h2v2h-2zM278 155h2v2h-2z" /></g>
    <g fill="#df8d6d"><path d="M65 158h2v2h-2zM150 163h2v2h-2zM280 160h2v2h-2z" /></g>
  </svg>;
}
