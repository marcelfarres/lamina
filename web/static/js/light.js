import * as THREE from 'three';
import {state, ST} from './state.js';
import {$, $$, esc} from './util.js';
import {inU, toMM} from './units.js';
import {record} from './history.js';
import {scene, renderer, camera, parts, ghost, hemi, dl, V3, paper} from './scene.js';
import {setTool} from './edit3d.js';

// ---------------------------------------------------------------- light
// The lights of the project: bulbs (all round) and spots (a cone) in and around the model, in a room whose floor, walls
// and ceiling catch their light and the shadows the parts throw — as a camera sees a lamp in a dark room. They are
// settings like any other: `state.light` (on or off) and `state.lights` (the list) are saved with the project and are
// steps of undo. They never reach the slicer (slice.js leaves them out) and a change to one never slices.
// A light is {on, like, kind, angle, soft, size, lm, color, pos, aim}: lengths in mm, `pos` from the middle of the
// model's footprint on the floor. Until one is changed there is no list: the one light is a small LED in the middle
// of the model, wherever that is, so a new model starts with its lamp in the right place.
//
// The picture: light falls off with the square of the distance, the view is tone-mapped (AgX) so a bright inside does
// not clip to flat colour, and the room gives a little light back. A source has a size, and its shadows are soft: the
// shadow tests of three.js are replaced (PCSS) by ones that find how far the part between the light and a point is, and
// blur by the source's size times how much farther the point is — sharp where a part meets the floor, wide on a far
// wall. The room is a box drawn from the inside: a wall between the camera and the model is seen from behind and not
// drawn, so the room can be looked into from any side. Off, nothing of it is on the scene and the view is as without it.
// The room is a setting too (`state.room`: shown or not, its size, walls, floor, the light the walls give back), and
// so is whether the assembly video is lit (`state.light_video`).
// ponytail: no tube or panel lights (three.js gives them no shadows), 4 lights at most (each is a shadow pass and a texture)
const MAX=4, MARK=['#E69F00','#56B4E9','#009E73','#CC79A7'];   // Okabe-Ito; a light is known by its number, the colour only helps
const WHITE={'#ffcf9e':'warm white, 2700 K','#ffe6cc':'neutral white, 4000 K','#eef2ff':'daylight, 6500 K'}, WARM='#ffcf9e';
const LIKE={led:['small LED',{kind:'bulb',size:6,lm:400}],filament:['LED filament bulb',{kind:'bulb',size:25,lm:500}],frosted:['frosted bulb',{kind:'bulb',size:45,lm:600}],
  gu10:['GU10 spot, 36°',{kind:'spot',angle:36,soft:25,size:50,lm:350}],desk:['desk lamp, 60°',{kind:'spot',angle:60,soft:40,size:40,lm:500}],own:['my own',{}]};
const AIM={up:'straight up',down:'straight down',middle:'the middle of the model',free:'a direction…'};
// a free direction: `tilt` from straight up (0) through level (90) to straight down (180), `turn` round the upright from x
// the tilt and turn a spot has now, whatever it points at: what the two sliders show, and where a move of one starts
const angles=l=>{if(l.aim==='free')return [l.tilt??45,l.turn??0]; if(l.aim!=='middle')return [l.aim==='down'?180:0,0];
  const v=new THREE.Vector3(-l.pos[0],-l.pos[1],(box?box.S.z/2:0)-l.pos[2]); if(v.length()<1)return [0,0]; v.normalize();
  return [Math.round(Math.acos(v.z)*180/Math.PI),Math.round((Math.atan2(v.y,v.x)*180/Math.PI+360)%360)]};
const aimOf=l=>{const t=(l.tilt??45)*Math.PI/180,f=(l.turn??0)*Math.PI/180;return new THREE.Vector3(Math.sin(t)*Math.cos(f),Math.sin(t)*Math.sin(f),Math.cos(t))};
const fresh=z=>({on:true,like:'led',kind:'bulb',angle:60,soft:30,size:6,lm:400,color:WARM,pos:[0,0,z],aim:'up'});
const WALLS={white:['white',0xf0eeea],grey:['light grey',0xa3a19e],dark:['dark',0x3b3a38]}, FLOOR={walls:['as the walls'],wood:['wood',0x9a6a40],dark:['dark',0x2c2b2a]};
const roomOf=()=>({show:true,size:2,walls:'white',floor:'walls',back:10,...state.room});
const key=()=>JSON.stringify([!!state.light,list(),ST.unit,state.room,state.light_video]);   // all the tab shows
let box=null, sel=0, shown='';   // the model's box at the last draw, the light the tab shows, and the list the tab was drawn from
const list=()=>state.lights||(box?[fresh(+(box.S.z/2).toFixed(1))]:[]);
const own=()=>state.lights||(state.lights=list());   // the first change makes the list the project's own

// ---- the 3D side
const lamp=new THREE.Group(), bounce=new THREE.HemisphereLight(0xffd6a8,0x5a4a3c,.1),   // what the lit walls give back, from above more than below
  wallMat=new THREE.MeshStandardMaterial({color:0xf0eeea,roughness:.95,side:THREE.BackSide}), floorMat=new THREE.MeshStandardMaterial({color:0xc9c2b8,roughness:.9,side:THREE.BackSide}),
  room=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),[wallMat,wallMat,wallMat,wallMat,wallMat,floorMat]);   // faces +x −x +y −y, ceiling, floor
let rigs=[], sig='', wasOn=false;
// Paper in a window: lit from behind, its far face takes the share of the light the paper lets through (`paper_through`),
// so a pane glows on the side away from the lamp. A pane casts a shadow and takes none.
// ponytail: so a part between the lamp and a pane does not darken it; a shadow lookup on the lit side if that shows
const through={value:.6};
paper.onBeforeCompile=sh=>{sh.uniforms.paperThrough=through; const was=THREE.ShaderChunk.lights_lambert_pars_fragment,
    now=was.replace('float dotNL = saturate( dot( geometryNormal, directLight.direction ) );','float paperD = dot( geometryNormal, directLight.direction ); float dotNL = paperD > 0. ? min( paperD, 1. ) : min( - paperD, 1. ) * paperThrough;');
  if(now===was)console.error('light: the Lambert code of three.js has changed; the paper does not glow');
  sh.fragmentShader='uniform float paperThrough;\n'+sh.fragmentShader.replace('#include <lights_lambert_pars_fragment>',now)};
// How much of the shade is paper: the panes' share of the panels' area (the panes and what holds them)
const ringA=r=>Math.abs(r.reduce((a,p,i)=>a+p[0]*r[(i+1)%r.length][1]-r[(i+1)%r.length][0]*p[1],0))/2, polyA=rs=>rs.reduce((a,[o,...h])=>a+ringA(o)-h.reduce((b,x)=>b+ringA(x),0),0);
function paperShare(){let pa=0,all=0; for(const s of ST.plan?.slices||[])for(const pc of s.pieces)for(const fc of pc.facets||[]){all+=polyA(fc.rings);if(fc.paper)pa+=polyA(fc.paper.rings)}
  return pa?Math.min(1,pa/all):0}
room.receiveShadow=true; bounce.position.set(0,0,1); lamp.add(bounce,room); lamp.visible=false; scene.add(lamp);
renderer.shadowMap.autoUpdate=false;   // the shadows are made again when something but the camera moved (the render loop)
renderer.toneMappingExposure=1.5;      // used only while the light tone-maps
// The soft tests. shadow.radius carries the source's size: for a bulb its radius in mm, for a spot its radius over the
// width of the shadow picture at the far plane (NEAR is the spot shadow camera's near / far, the same number in both
// places, so a stored depth can be read as a distance). Both take samples on a spiral turned by a random angle at each
// pixel, and the mean of the pixel and its two neighbours in the GPU's 2x2 quad: a wide soft edge shows as fine grain,
// as in a photo. One fixed spiral drew a wide edge as 32 streaks; an angle from interleaved gradient noise, as diagonal
// hatching (it is made for renderers that average frames, and this view draws one).
const NEAR=.005, SPOT=`float lampSpin() { return 6.2831853 * fract( sin( dot( gl_FragCoord.xy, vec2( 12.9898, 78.233 ) ) ) * 43758.5453 ); }
	float lampQuad( float lit ) { vec2 q = mod( floor( gl_FragCoord.xy ), 2.0 ) - 0.5; return lit - ( dFdx( lit ) * q.x + dFdy( lit ) * q.y ) * 0.6667; }
	float getShadow( sampler2D shadowMap, vec2 shadowMapSize, float shadowBias, float shadowRadius, vec4 shadowCoord ) {
		shadowCoord.xyz /= shadowCoord.w; shadowCoord.z += shadowBias;
		const float N = ${NEAR};
		float lit = 1.0, zr = shadowCoord.z, spin = lampSpin();
		if ( shadowCoord.x >= 0.0 && shadowCoord.x <= 1.0 && shadowCoord.y >= 0.0 && shadowCoord.y <= 1.0 && zr <= 1.0 ) {
			float dr = N / ( 1.0 - zr * ( 1.0 - N ) ), search = min( 0.06, 30.0 * shadowRadius ), sum = 0.0, n = 0.0;
			for ( int i = 0; i < 16; i ++ ) {
				float r = sqrt( ( float( i ) + 0.5 ) / 16.0 ) * search, a = float( i ) * 2.39996 + spin;
				float z = unpackRGBAToDepth( texture2D( shadowMap, shadowCoord.xy + vec2( cos( a ), sin( a ) ) * r ) );
				if ( z < zr ) { sum += N / ( 1.0 - z * ( 1.0 - N ) ); n += 1.0; }
			}
			if ( n > 0.0 ) {
				float db = sum / n, pen = max( shadowRadius * ( dr - db ) / ( db * dr ), 1.5 / shadowMapSize.x );
				lit = 0.0;
				for ( int i = 0; i < 32; i ++ ) {
					float r = sqrt( ( float( i ) + 0.5 ) / 32.0 ) * pen, a = float( i ) * 2.39996 + spin;
					lit += texture2DCompare( shadowMap, shadowCoord.xy + vec2( cos( a ), sin( a ) ) * r, zr );
				}
				lit /= 32.0;
			}
		}
		return lampQuad( lit );
	}
`, BULB=`float getPointShadow( sampler2D shadowMap, vec2 shadowMapSize, float shadowBias, float shadowRadius, vec4 shadowCoord, float shadowCameraNear, float shadowCameraFar ) {
	float texelY = 1.0 / ( shadowMapSize.y * 2.0 ), range = shadowCameraFar - shadowCameraNear, R = shadowRadius;
	float dr = length( shadowCoord.xyz ), dp = ( dr - shadowCameraNear ) / range + shadowBias, spin = lampSpin();
	vec3 d = shadowCoord.xyz / dr, t = normalize( cross( d, abs( d.z ) < 0.9 ? vec3( 0.0, 0.0, 1.0 ) : vec3( 1.0, 0.0, 0.0 ) ) ), b = cross( d, t );
	float search = 0.5 * max( 1.0 - 2.0 * R / dr, 0.0 ), sum = 0.0, n = 0.0;   // where a part at least 2 R from the bulb's centre can hide some of the bulb
	for ( int i = 0; i < 16; i ++ ) {
		float r = sqrt( ( float( i ) + 0.5 ) / 16.0 ) * search, a = float( i ) * 2.39996 + spin;
		float z = unpackRGBAToDepth( texture2D( shadowMap, cubeToUV( d + ( t * cos( a ) + b * sin( a ) ) * r, texelY ) ) );
		if ( z < dp ) { sum += z; n += 1.0; }
	}
	float lit = 1.0;   // nothing in the way: no return here, the quad's mean needs every pixel of it to get to the end
	if ( n > 0.0 ) {
		float db = shadowCameraNear + sum / n * range, pen = max( R * ( dr - db ) / ( db * dr ), 6.0 * texelY );
		lit = 0.0;
		for ( int i = 0; i < 32; i ++ ) {
			float r = sqrt( ( float( i ) + 0.5 ) / 32.0 ) * pen, a = float( i ) * 2.39996 + spin;
			lit += texture2DCompare( shadowMap, cubeToUV( d + ( t * cos( a ) + b * sin( a ) ) * r, texelY ), dp );
		}
		lit /= 32.0;
	}
	return lampQuad( lit );
}
#endif`;
{const was=THREE.ShaderChunk.shadowmap_pars_fragment, spot=was.replace(/float getShadow\([\s\S]*?(?=vec2 cubeToUV)/,SPOT+'\t'), both=spot.replace(/float getPointShadow\([\s\S]*#endif$/,BULB);
  if(spot===was||both===spot)console.error('light: the shadow code of three.js has changed; the soft shadows are off'); else THREE.ShaderChunk.shadowmap_pars_fragment=both}
function disc(draw){const c=document.createElement('canvas');c.width=c.height=64;draw(c.getContext('2d'));const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;return t}
const glowTex=disc(g=>{const r=g.createRadialGradient(32,32,0,32,32,32);r.addColorStop(0,'rgba(255,255,255,1)');r.addColorStop(.15,'rgba(255,255,255,.4)');r.addColorStop(1,'rgba(255,255,255,0)');g.fillStyle=r;g.fillRect(0,0,64,64)});
// one light on the scene: the light, the white-hot source with its glow, and — while the Light tab is open — its
// number and, for a spot, the outline of its cone
function rig(l,i,small,soft){if(!l.on)return null; const spot=l.kind==='spot', light=spot?new THREE.SpotLight(0xffffff,1,0,1,0,2):new THREE.PointLight(0xffffff,1,0,2);
  light.castShadow=true; light.shadow.normalBias=.3; light.shadow.bias=spot?-.0002:-.001; light.shadow.mapSize.setScalar(spot?2048:small?512:1024);
  const g={light,ball:new THREE.Mesh(new THREE.SphereGeometry(1,24,16),new THREE.MeshBasicMaterial({color:0xfff6e8,toneMapped:false})),
    glow:new THREE.Sprite(new THREE.SpriteMaterial({map:glowTex,blending:THREE.AdditiveBlending,depthWrite:false,toneMapped:false})),
    tag:new THREE.Sprite(new THREE.SpriteMaterial({depthTest:false,toneMapped:false,map:disc(c=>{c.fillStyle='#0f1012';c.beginPath();c.arc(32,32,28,0,7);c.fill();c.strokeStyle=MARK[i];c.lineWidth=6;c.stroke();
      c.fillStyle='#fff';c.font='bold 36px system-ui,sans-serif';c.textAlign='center';c.textBaseline='middle';c.fillText(i+1,32,34)})})),
    cone:spot?new THREE.LineSegments(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:MARK[i],depthTest:false,toneMapped:false,transparent:true,opacity:.85})):null};
  // what the panes let through, back as even light with no shadows: the shade is a soft source, the window pattern is gone
  // ponytail: a bulb only, and nothing stands in this light's way; a spot's light stops at the paper
  if(soft&&!spot)light.add(g.soft=new THREE.PointLight(0xffffff,0,0,2));
  g.tag.renderOrder=20; lamp.add(light,g.ball,g.glow,g.tag); if(spot){g.cone.renderOrder=19;lamp.add(light.target,g.cone)} return g}
function unrig(g){if(!g)return; g.light.shadow.dispose(); g.tag.material.map.dispose(); g.cone?.geometry.dispose(); lamp.remove(g.light,g.ball,g.glow,g.tag); if(g.cone)lamp.remove(g.light.target,g.cone)}
export function applyLight(){const on=!!state.light, tool=ST.tool==='light', tab=($('section[data-tab="light"]').classList.contains('on')||tool)&&!ST.recording; $('#lamp').checked=on;
  // the move-a-light tool is there while the light is on; the column is there while it holds a tool to choose
  $('#tools button[data-tool=light]').hidden=!on; $('#tools').hidden=!$$('#tools button').some(b=>b.dataset.tool&&!b.hidden); if(tool&&!on)return setTool('');
  $('#lighthint').hidden=!tool; arrows.visible=aimDot.visible=false;
  const b=new THREE.Box3(); for(const m of parts.children)if(m.userData.group!=='B')b.expandByObject(m);   // every part, shown or not: the room stays put while the steps run
  if(b.isEmpty())b.setFromObject(ghost); if(b.isEmpty())return;
  const c=b.getCenter(new THREE.Vector3()),S=b.getSize(new THREE.Vector3()),r=S.length(),O=new THREE.Vector3(c.x,c.y,b.min.z); box={S,r};   // off too: the tab shows the light a tick would turn on
  const P_=ST.plan?.params||{}, share=paperShare(); through.value=(P_.paper_through??60)/100; paper.color.set(P_.paper_color||'#fff1d0');
  if(on){const L=list(), s=L.map(l=>l.on?l.kind:'-').join()+(share>0);
    if(s!==sig){rigs.forEach(unrig); const small=L.filter(l=>l.on&&l.kind==='bulb').length>2; rigs=L.map((l,i)=>rig(l,i,small,share>0)); sig=s}
    // the room holds the model with air round it, and every light: one put outside the model is still inside the room
    const Rm=roomOf(); let half=r*.45*Rm.size, high=r*.8*Rm.size; for(const l of L){half=Math.max(half,Math.abs(l.pos[0])+r*.3,Math.abs(l.pos[1])+r*.3);high=Math.max(high,l.pos[2]+r*.3)}
    const K=3*(r*.9)**2/400, far=Math.hypot(2*half,2*half,high)*1.05;   // 400 lm on a wall half a room away is about as bright at any size of model
    rigs.forEach((g,i)=>{if(!g)return; const l=L[i],P=O.clone().add(V3(l.pos)),R=l.size/2;
      g.light.color.set(l.color); g.light.position.copy(P); g.light.shadow.camera.far=far;
      g.ball.position.copy(P); g.ball.scale.setScalar(R); g.glow.position.copy(P); g.glow.scale.setScalar(R*3+r*.06); g.glow.material.color.set(l.color);
      g.tag.visible=tab; g.tag.position.copy(P).z+=R+r*.05; g.tag.scale.setScalar(r*.07);
      if(l.kind==='bulb'){g.light.intensity=K*l.lm; g.light.shadow.radius=R; if(g.soft){g.soft.color.copy(g.light.color).multiply(paper.color); g.soft.intensity=K*l.lm*share*through.value}}
      else{const a=Math.min(l.angle,170)*Math.PI/360, A=l.aim==='middle'&&P.distanceTo(c)>1?c.clone():P.clone().add(l.aim==='free'?aimOf(l):new THREE.Vector3(0,0,l.aim==='down'?-1:1)), dir=A.clone().sub(P).normalize();
        // the same lumens in a narrower cone are brighter along it
        // ponytail: at most 8 times a bulb's, or a narrow spot burns the picture white; real exposure would follow the scene
        g.light.intensity=K*l.lm*Math.min(8,2/(1-Math.cos(a))); g.light.angle=a; g.light.penumbra=l.soft/100; g.light.target.position.copy(A); g.light.target.updateMatrixWorld();
        g.light.shadow.camera.near=far*NEAR; g.light.shadow.radius=R/(2*Math.tan(a)*far);
        const len=r*.3, w=Math.tan(a)*len, u=new THREE.Vector3().crossVectors(dir,Math.abs(dir.z)<.9?new THREE.Vector3(0,0,1):new THREE.Vector3(1,0,0)).normalize(), v=new THREE.Vector3().crossVectors(dir,u), pts=[],
          ring=k=>P.clone().addScaledVector(dir,len).addScaledVector(u,w*Math.cos(k*Math.PI/20)).addScaledVector(v,w*Math.sin(k*Math.PI/20));
        for(let k=0;k<40;k++){pts.push(ring(k),ring(k+1)); if(k%5===0)pts.push(P,ring(k))}
        g.cone.geometry.setFromPoints(pts); g.cone.visible=tab; g.tip=P.clone().addScaledVector(dir,len)}   // the tip: where the tool takes hold to aim it
      g.light.shadow.camera.updateProjectionMatrix()});
    room.scale.set(half*2,half*2,high); room.position.set(c.x,c.y,b.min.z-r*.002+high/2); room.visible=Rm.show; bounce.intensity=Rm.back/100;
    wallMat.color.set(WALLS[Rm.walls][1]); Rm.floor==='walls'?floorMat.color.copy(wallMat.color).multiplyScalar(.85):floorMat.color.set(FLOOR[Rm.floor][1]);
    const g=tool&&rigs[sel]; if(g){arrows.visible=true;arrows.position.copy(g.light.position);arrows.scale.setScalar(r*.22);
      if(g.tip){aimDot.visible=true;aimDot.position.copy(g.tip);aimDot.scale.setScalar(r*.014)}}}
  for(const m of parts.children){m.castShadow=m.receiveShadow=on&&m.userData.group!=='B'; if(m.userData.pane)m.userData.pane.castShadow=on}
  lamp.visible=on; renderer.shadowMap.enabled=on; renderer.toneMapping=on?THREE.AgXToneMapping:THREE.NoToneMapping;
  hemi.intensity=on?0:1.1; dl.intensity=on?0:1.2; scene.background.set(on?0x050506:0x141517);
  if(on!==wasOn){wasOn=on; for(const m of [...parts.children,room])for(const x of [m.material].flat())x.needsUpdate=true}   // the shaders gain or lose the shadow lookup
  if(key()!==shown)renderTab();   // an undo, an opened project, a new model, other units: the tab follows
  ST.dirty=true}

// ---- the Light tab, in the rows the other tabs are made of
const sl=(k,v,lo,hi,step=1)=>`<span class="sl"><input type="range" id="lt_${k}_r" value="${v}" min="${lo}" max="${hi}" step="${step}" data-for="lt_${k}"><input type="number" id="lt_${k}" value="${v}" min="${lo}" max="${hi}" step="${step}" data-l="${k}"></span>`;
const pick=(k,opts,v)=>`<select data-l="${k}">${Object.entries(opts).map(([x,t])=>`<option value="${esc(x)}" ${x===v?'selected':''}>${esc(t)}</option>`).join('')}</select>`;
const row=(k,label,tip,inp,cls='')=>`<div class="f ${cls}" data-p="light_${k}"><span class="k" data-tip="${esc(tip)}">${label}</span>${inp}</div>`;
const MORE='<button class="more" hidden></button></div>';   // the foot every group of settings has (form.js counts on it)
const rows=L=>{const u=ST.unit;return L.map((x,i)=>`<div class="lrow${i===sel?' sel':''}${x.on?'':' off'}" data-li="${i}">
      <input type="checkbox" data-on="${i}" ${x.on?'checked':''} title="this light on or off" aria-label="light ${i+1} on"><span class="ln" style="border-color:${MARK[i]}">${i+1}</span>
      <span>${x.kind==='spot'?'Spot':'Bulb'}<small>${x.like in LIKE&&x.like!=='own'?esc(LIKE[x.like][0]):x.kind==='spot'?`${x.angle}° cone`:`${inU(x.size)} ${u} across`}${x.kind==='spot'?` · ${AIM[x.aim]}`:''} · ${x.lm} lm${x.on?'':' · off'}</small></span>
      <span><button class="small" data-act="copy" data-i="${i}" title="a copy of this light" ${L.length<MAX?'':'disabled'}>⧉</button><button class="small" data-act="del" data-i="${i}" title="remove this light">✕</button></span></div>`).join('')};   // the list: drawn again on its own while a slider moves, so a row says what its light is now
function renderTab(){const Rm=roomOf(), L=list(), on=!!state.light, u=ST.unit, lim=box?Math.ceil(inU(box.r*2)):300, st=inU(1)<1?.01:1; sel=Math.max(0,Math.min(sel,L.length-1)); shown=key();
  const l=L[sel], spot=l?.kind==='spot';
  $('#g-light').innerHTML=row('show','show the light','Light the model from the lights below and show the shadows it throws, in a room. The same tick as 💡 light over the 3D view',`<input type="checkbox" id="light_on" ${on?'checked':''}>`)
    +`<div class="sec" data-sec="Lights"><h3 class="sub" title="click to fold or unfold">Lights<small></small></h3><div class="llist">${rows(L)}</div>
      <button class="small" data-act="add" ${L.length<MAX?'':`disabled title="${MAX} lights at most: each one is a shadow to work out"`}>＋ add a light</button>${MORE}`
    +(l?`<div class="sec" data-sec="Light"><h3 class="sub" title="click to fold or unfold">Light ${sel+1}<small></small></h3>`
      +row('like','like','A real lamp to start from: it sets the kind, the size, the brightness and, for a spot, the cone. Change any of them and this reads “my own”',pick('like',Object.fromEntries(Object.entries(LIKE).map(([k,v])=>[k,v[0]])),l.like))
      +row('kind','kind','A bulb shines all round. A spot shines in a cone',pick('kind',{bulb:'bulb: all round',spot:'spot: a cone'},l.kind))
      +(spot?row('angle','beam angle (°)','How wide the cone of a spot is, edge to edge',sl('angle',l.angle,5,160),'dep')
        +row('soft','soft edge (%)','How much of the cone fades out toward its edge: 0 is a hard circle of light',sl('soft',l.soft,0,100),'dep')
        +row('aim','points at','Where the spot points. With the move a light tool, drag the dot at the end of its cone',pick('aim',AIM,l.aim),'dep')
        +row('tilt','tilt (°)','How far the spot leans from straight up: 0 is up, 90 is level, 180 is down. Moving it aims the spot in a direction of its own',sl('tilt',angles(l)[0],0,180),'dep')
        +row('turn','turn (°)','Which way the spot leans, round the upright: 0 is along x, 90 along y',sl('turn',angles(l)[1],0,360),'dep'):'')
      +row('size',`source size (${u})`,'How big the part that shines is, across. A small source throws a sharp pattern, a big one a soft one',sl('size',inU(l.size),inU(1),inU(120),st))
      +row('lm','brightness (lm)','The light it gives, in lumens, as on the box of a real lamp: 400 lm is a 40 W bulb',sl('lm',l.lm,10,1600,10))
      +row('color','colour','The colour of the light: a white of a real lamp, or any colour',`<span>${pick('color',{...WHITE,pick:'a colour…'},l.color in WHITE?l.color:'pick')} <input type="color" data-l="hex" value="${esc(l.color)}" ${l.color in WHITE?'hidden':''} aria-label="the colour of the light"></span>`)
      +`<div class="f wide" data-p="light_pos"><span class="k" data-tip="Where the light is: x and y from the middle of the model, z up from the floor it stands on. A light can be outside the model">where it is (${u})</span><div class="rows">${['x','y','z'].map((a,j)=>`<div class="r"><small>${a}</small>${sl('p'+j,inU(l.pos[j]),j<2?-lim:0,lim,st)}</div>`).join('')}</div></div>${MORE}`:'')
    +`<div class="sec" data-sec="Room"><h3 class="sub" title="click to fold or unfold">Room<small></small></h3>`
      +row('room_show','show the room','The floor, walls and ceiling that catch the light. Off, the lights still light the model, in the dark',`<input type="checkbox" data-r="show" ${Rm.show?'checked':''}>`)
      +row('room_size','size (× the model)','How big the room is beside the model. In a big room the pattern on the walls is larger and fainter. A light outside the room makes it grow',sl('r_size',Rm.size,1,6,.5))
      +row('room_walls','walls','The colour of the walls and the ceiling',pick('r_walls',Object.fromEntries(Object.entries(WALLS).map(([k,v])=>[k,v[0]])),Rm.walls))
      +row('room_floor','floor','The colour of the floor',pick('r_floor',Object.fromEntries(Object.entries(FLOOR).map(([k,v])=>[k,v[0]])),Rm.floor))
      +row('room_back','light back from the walls (%)','How much the room lights what the lights do not reach: 0 is a black shadow, more is a softer one',sl('r_back',Rm.back,0,40))+MORE
    +`<div class="sec" data-sec="Picture"><h3 class="sub" title="click to fold or unfold">Picture<small></small></h3>`
      +row('picture','picture','The 3D view as it is now, as a PNG file',`<button class="small" data-act="png">save the view as a picture (PNG)</button>`)
      +row('video','light in the assembly video','The assembly video of the Export tab is lit as the view is. Off, it is recorded without the light',`<input type="checkbox" id="light_video" ${state.light_video===false?'':'checked'}>`)+MORE}
function touch(redraw){if(redraw)renderTab(); else{shown=key();$('#g-light .llist').innerHTML=rows(list())}   // a slider being dragged keeps its row: the tab is not drawn again under it
  applyLight(); clearTimeout(touch.t); touch.t=setTimeout(record,400)}   // a slider drag is one step of undo
$('#g-light').addEventListener('input',e=>{const t=e.target,k=t.dataset.l; if(!k||t.type==='range')return;
  if(k[1]==='_'){state.room={...roomOf(),[k.slice(2)]:t.tagName==='SELECT'?t.value:+t.value};return touch()}   // a setting of the room
  const l=own()[sel],v=+t.value||0;   // a slider writes its number box, which lands here
  if(t.tagName==='SELECT'){if(k==='like')Object.assign(l,LIKE[t.value][1],{like:t.value}); else if(k==='color'){if(t.value!=='pick')l.color=t.value; else if(l.color in WHITE)l.color='#ff8040'} else{l[k]=t.value;if(k==='kind')l.like='own'}
    return touch(1)}   // a choice can add or take rows: the tab is drawn again
  if(k==='tilt'||k==='turn'){[l.tilt,l.turn]=angles(l); l[k]=v; l.aim='free'; $('#g-light select[data-l=aim]').value='free'; return touch()}   // from where it points now, in a direction of its own
  if(k==='hex')l.color=t.value; else if(k[0]==='p')l.pos[+k[1]]=toMM(v); else{l[k]=k==='size'?toMM(v):v; l.like='own'; $('#g-light select[data-l=like]').value='own'}
  touch()});
$('#g-light').addEventListener('change',e=>{const t=e.target; if(t.id==='light_on'){state.light=t.checked;return touch()} if(t.id==='light_video'){state.light_video=t.checked;return touch()} if(t.dataset.r){state.room={...roomOf(),show:t.checked};return touch()} if(t.dataset.on){own()[+t.dataset.on].on=t.checked;touch(1)}});
$('#g-light').addEventListener('click',e=>{const t=e.target,a=t.dataset.act,r=t.closest('.lrow'); if(t.dataset.on)return;
  if(a==='png')return snap();
  if(a){const L=own(),i=+t.dataset.i; if(a==='del')L.splice(i,1); else if(L.length<MAX){L.push(a==='copy'?structuredClone(L[i]):fresh(+(box.S.z/2).toFixed(1)));const n=L.at(-1);n.pos[0]+=a==='copy'?Math.round(box.r*.2):0;sel=L.length-1}
    return touch(1)}
  if(r&&+r.dataset.li!==sel){sel=+r.dataset.li;shown='';applyLight()}});
// the view as a picture: drawn once more without the lights' numbers and cones, and read before the browser clears it
function snap(){for(const g of rigs)if(g){g.tag.visible=false;if(g.cone)g.cone.visible=false} arrows.visible=false; renderer.render(scene,camera);
  const a=document.createElement('a'); a.href=renderer.domElement.toDataURL('image/png'); a.download=`${(state.project||'lamina').replace(/\W+/g,'_')}_light.png`; a.click(); applyLight()}
// ---- the move-a-light tool: a light is taken by its place on the screen (a small LED is too small to aim a ray at) and
// dragged across the view, or by one of the three arrows of the light picked, along that arrow. A click picks a light.
// A drag that starts on neither turns the view as ever.
const arrows=new THREE.Group(), AX=[[1,0,0],[0,1,0],[0,0,1]], aimDot=new THREE.Mesh(new THREE.SphereGeometry(1,16,12),new THREE.MeshBasicMaterial({color:0xffffff,depthTest:false,toneMapped:false})); let pull=null;
aimDot.renderOrder=30; aimDot.visible=false; lamp.add(aimDot);
AX.forEach((d,i)=>{const a=new THREE.ArrowHelper(V3(d),new THREE.Vector3(),1,[0xff5c5c,0x5cff7a,0x5c9cff][i],.28,.14);a.traverse(o=>{o.renderOrder=30;if(o.material){o.material.depthTest=false;o.material.toneMapped=false}});arrows.add(a)});
arrows.visible=false; lamp.add(arrows);
const px=(P,rc)=>{const q=P.clone().project(camera);return [rc.left+(q.x+1)/2*rc.width,rc.top+(1-q.y)/2*rc.height]};   // a point of the scene on the screen
{const cv=renderer.domElement;
  cv.addEventListener('pointerdown',ev=>{if(ST.tool!=='light'||ev.button!==0||!state.light)return; const rc=cv.getBoundingClientRect(),m=[ev.clientX,ev.clientY],g=rigs[sel]; let hit=null;
    if(g?.tip){const A=px(g.tip,rc);if(Math.hypot(m[0]-A[0],m[1]-A[1])<13)hit={i:sel,aim:true}}   // the dot at the end of a spot's cone: it is aimed
    if(g&&!hit)AX.forEach((d,i)=>{const A=px(g.light.position,rc),B=px(g.light.position.clone().addScaledVector(V3(d),arrows.scale.x),rc),ux=B[0]-A[0],uy=B[1]-A[1],n=ux*ux+uy*uy||1,t=((m[0]-A[0])*ux+(m[1]-A[1])*uy)/n;
      if(t>.3&&t<1.1&&Math.hypot(m[0]-A[0]-t*ux,m[1]-A[1]-t*uy)<9)hit={i:sel,axis:i,ux,uy,n}});   // the outer part of an arrow: its foot is the light's own
    if(!hit)rigs.forEach((x,i)=>{if(!x)return;const A=px(x.light.position,rc),d=Math.hypot(m[0]-A[0],m[1]-A[1]);if(d<20&&(!hit||d<hit.d))hit={i,d}});
    if(!hit)return; ev.stopImmediatePropagation(); cv.setPointerCapture(ev.pointerId);   // taken: the view does not turn and no part is picked
    const P=rigs[hit.i].light.position.clone(); pull={...hit,m,P,pos:[...list()[hit.i].pos],moved:false,plane:new THREE.Plane().setFromNormalAndCoplanarPoint(camera.getWorldDirection(new THREE.Vector3()),hit.aim?rigs[hit.i].tip:P)}},true);
  cv.addEventListener('pointermove',ev=>{if(!pull)return; ev.stopImmediatePropagation(); const dx=ev.clientX-pull.m[0],dy=ev.clientY-pull.m[1]; if(!pull.moved&&Math.hypot(dx,dy)<4)return; pull.moved=true;
    const under=()=>{const rc=cv.getBoundingClientRect(),ray=new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2((ev.clientX-rc.left)/rc.width*2-1,1-(ev.clientY-rc.top)/rc.height*2),camera); return ray.ray.intersectPlane(pull.plane,new THREE.Vector3())};
    if(pull.aim){const at=under(); if(!at)return; const v=at.sub(pull.P).normalize(),l=own()[pull.i];
      l.aim='free'; l.tilt=Math.round(Math.acos(Math.max(-1,Math.min(1,v.z)))*180/Math.PI); l.turn=Math.round((Math.atan2(v.y,v.x)*180/Math.PI+360)%360); return touch(1)}
    let d; if(pull.axis!==undefined)d=V3(AX[pull.axis]).multiplyScalar((dx*pull.ux+dy*pull.uy)/pull.n*arrows.scale.x);
    else{const at=under(); if(!at)return; d=at.sub(pull.P)}
    const l=own()[pull.i]; sel=pull.i; l.pos=[0,1,2].map(j=>+(pull.pos[j]+d.getComponent(j)).toFixed(1)); l.pos[2]=Math.max(0,l.pos[2]); touch(1)},true);   // never under the floor
  cv.addEventListener('pointerup',ev=>{if(!pull)return; ev.stopImmediatePropagation(); const p=pull; pull=null; if(!p.moved&&p.i!==sel){sel=p.i;shown='';applyLight()}},true)}
$('#lamp').onchange=e=>{state.light=e.target.checked;touch(1)};
// what the other modules ask of the light, through ST (they are loaded before this one): () the parts or the tab on
// show changed, ('reset') the tab's reset button: everything the tab holds back to its default, the light off too
ST.light=what=>{if(what==='reset'){for(const k of ['light','lights','room','light_video'])delete state[k];sel=0;return touch(1)} applyLight()};
