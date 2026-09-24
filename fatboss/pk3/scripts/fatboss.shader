// FatBoss: first-person sleeves drawn from both sides.
// The sleeve meshes are open tubes; while the weapon inspect turns a weapon,
// the camera can look into a sleeve and its culled inner faces made it look
// see-through. Same texture and lighting as the implicit shaders otherwise.

models/weapons2/arms/arm_allied
{
	cull none
	{
		map models/weapons2/arms/arm_allied.tga
		rgbGen lightingDiffuse
	}
}

models/weapons2/arms/arm_axis
{
	cull none
	{
		map models/weapons2/arms/arm_axis.tga
		rgbGen lightingDiffuse
	}
}

models/weapons2/knife/arm2
{
	cull none
	{
		map models/weapons2/knife/arm2.tga
		rgbGen lightingDiffuse
	}
}

// Invisible: the weapon inspect maps a support hand to this to show the
// weapon in one hand (see the one-hand skins in models/fatboss).
models/fatboss/nodraw
{
	nopicmip
	{
		map $whiteimage
		blendFunc GL_ZERO GL_ONE
	}
}
