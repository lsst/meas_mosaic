import os, sys, math
import datetime
import eups
import lsst.afw.image                    as afwImage
import lsst.daf.base                     as dafBase
import lsst.afw.cameraGeom               as cameraGeom
import lsst.afw.cameraGeom.utils         as cameraGeomUtils
import lsst.pex.policy                   as pexPolicy
import hsc.camera.data                   as data
import hsc.meas.mosaic.mosaicLib         as hscMosaic
import hsc.meas.mosaic.stack             as stack

def getBasename(exposureId, ccdId):
    rootdir = "/data/yasuda/data_cosmos"
    
    basename = "%s/dith%d/out-ssb_ccd%03d" % (rootdir, int(exposureId), int(ccdId))

    return basename

def getOutputFileName(outputDir, exposureId, ccdId):
    #fname = "dith%d_ccd%03d-wcsh.fits" % (int(exposureId), int(ccdId))
    fname = "HSCA%05d%03d-wcsh.fits" % (int(exposureId), int(ccdId))

    return os.path.join(outputDir, fname)

def mosaic(ditherIds, ccdIds, fitFP, outputDir=".", rerun="cpl-0017"):
    mgr = data.Manager(instrument="HSC", rerun=rerun)
    camera = cameraGeomUtils.makeCamera(mgr.getGeomPolicy())
    
    #rootdir = "/data/yasuda/data_cosmos"

    # Setup wcs dictionary
    print "Reading WCS ..."
    wcsDic = hscMosaic.WcsDic()
    if fitFP:
        for ditherId in ditherIds:
            ccdId = ccdIds[0]
            fname = mgr.getCorrFilename(int(ditherId), int(ccdId))
            metadata = afwImage.readMetadata(fname)
            wcs = afwImage.makeWcs(metadata)
            ccd = cameraGeomUtils.findCcd(camera, cameraGeom.Id(int(ccdId)))
            offset = ccd.getCenter()
            wcs.shiftReferencePixel(offset[0], offset[1])
            wcsDic[ditherIds.index(ditherId)] = wcs
    else:
        iframe = 0
        for ditherId in ditherIds:
            for ccdId in ccdIds:
                fname = mgr.getCorrFilename(int(ditherId), int(ccdId))
                metadata = afwImage.readMetadata(fname)
                wcs = afwImage.makeWcs(metadata)
                wcsDic[iframe] = wcs
                iframe += 1
    print datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")
        
    sourceSet = []
    matchList = []
    dims = []

    print "Reading catalogs ..."
    iframe = 0
    for ditherId in ditherIds:
        for ccdId in ccdIds:
            basename = os.path.join(mgr.getOutputDirname(int(ditherId), int(ccdId), dirType="misc"),
                                    "HSCA%05d%03d" % (int(ditherId), int(ccdId)))
            #sS, mL, hdrInfo = pipe.io.readFits(basename)
            if os.path.isfile("%s.fits" % (basename)):
                sS = hscMosaic.readCat("%s.fits" % (basename))
            else:
                sS = []
            if os.path.isfile("%s.match.fits" % (basename)):
                mL = hscMosaic.readMatchList("%s.match.fits" % (basename))
            else:
                mL = []
            fname = mgr.getCorrFilename(int(ditherId), int(ccdId))
            metadata = afwImage.readMetadata(fname)
            dims.append([metadata.get("NAXIS1"), metadata.get("NAXIS2")])
            
            ccd = cameraGeomUtils.findCcd(camera, cameraGeom.Id(int(ccdId)))
            offset = ccd.getCenter()
            
            for s in sS:
                if fitFP:
                    x = s.getXAstrom()
                    y = s.getYAstrom()
                    s.setXAstrom(x + offset[0])
                    s.setYAstrom(y + offset[1])
                    c = wcsDic[ditherIds.index(ditherId)].pixelToSky(s.getXAstrom(), s.getYAstrom())
                else:
                    c = wcsDic[iframe].pixelToSky(s.getXAstrom(), s.getYAstrom())
                s.setRa(c[0])
                s.setDec(c[1])
                if fitFP:
                    s.setAmpExposureId(ditherIds.index(ditherId))
                else:
                    s.setAmpExposureId(iframe)

            for m in mL:
                ra = m.first.getRa()
                dec = m.first.getDec()
                if fitFP:
                    x2, y2 = wcsDic[ditherIds.index(ditherId)].skyToPixel(ra, dec)
                    x = m.second.getXAstrom()
                    y = m.second.getYAstrom()
                    m.second.setXAstrom(x + offset[0])
                    m.second.setYAstrom(y + offset[1])
                    m.second.setAmpExposureId(ditherIds.index(ditherId))
                else:
                    x2, y2 = wcsDic[iframe].skyToPixel(ra, dec)
                    m.second.setAmpExposureId(iframe)
                x = m.second.getXAstrom()
                y = m.second.getYAstrom()
                if (math.fabs(x2-x) > 1.0 or math.fabs(y2-y) > 1.0):
                    m.second.setFlagForWcs(1)

            sourceSet.append(sS)
            matchList.append(mL)

            iframe += 1

    print datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")

    productDir = eups.productDir("hscMosaic")
    policyPath = os.path.join(productDir, "policy", "HscMosaicDictionary.paf")
    policy = pexPolicy.Policy.createPolicy(policyPath)

    print "Merge matched catalog ..."
    allMat = hscMosaic.mergeMat(matchList)
    print 'len(allMat) = ', len(allMat)
    print datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")

    print "Merge source catalog ..."
    d_lim = 3.0 / 3600.0 * math.pi / 180.0
    nbrightest = policy.get("nBrightest")
    allSource = hscMosaic.mergeSource(sourceSet, allMat, d_lim, nbrightest)
    print 'len(allSource) = ', len(allSource)
    print datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")

    print "Solve mosaic ..."
    order = policy.get("fittingOrder")
    internal = policy.get("internalFitting")
    print "order : ", order, " internal : ", internal
    verbose = False
    fscale = hscMosaic.solveMosaic(order, allMat, allSource, wcsDic, internal, verbose)
    print datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")

    writeNewWCS(ditherIds, ccdIds, fitFP, wcsDic, fscale, dims, camera, outputDir)

    outputDiag("mosaicFitTest.dat", allMat, allSource, wcsDic, internal, outputDir)

    ##if writeNewFits:
    ##    writeNewFitsFiles(ditherIds, ccdIds, wcsDic, fscale, rootdir, outputName)

def outputDiag(ofname, allMat, allSource, wcsDic, internal, workDir="."):
    print "Output Diagnostic ..."
    f = open(os.path.join(workDir, ofname), 'w')
    for mL in allMat:
        if mL[0].getFlagForWcs():
            continue
        ra = mL[0].getRa() * 180. / math.pi
        dec = mL[0].getDec() * 180. / math.pi
        for i in range(1,len(mL)):
            if mL[i].getFlagForWcs():
                continue
            ditherId = mL[i].getAmpExposureId()
            x = mL[i].getXAstrom()
            y = mL[i].getYAstrom()
            if mL[i].getPsfFlux() > 0.0:
                mag = -2.5 * math.log10(mL[i].getPsfFlux())
            else:
                mag = 99.
            x0, y0 = wcsDic[ditherId].skyToPixel(ra, dec)
            line = "m %d %9.5f %9.5f %9.3f %9.3f %9.3f %9.3f %6.3f %6.3f %7.3f\n" % (ditherId, ra, dec, x0, y0, x, y, x-x0, y-y0, mag)
            f.write(line)

    if internal:
        for sS in allSource:
            if sS[0].getFlagForWcs():
                continue
            ra = sS[0].getRa() * 180. / math.pi
            dec = sS[0].getDec() * 180. / math.pi
            for i in range(1,len(sS)):
                if sS[i].getFlagForWcs():
                    continue
                ditherId = sS[i].getAmpExposureId()
                x = sS[i].getXAstrom()
                y = sS[i].getYAstrom()
                if sS[i].getPsfFlux() > 0:
                    mag = -2.5 * math.log10(sS[i].getPsfFlux())
                else:
                    mag = 99.
                x0, y0 = wcsDic[ditherId].skyToPixel(ra, dec)
                line = "s %d %9.5f %9.5f %9.3f %9.3f %9.3f %9.3f %6.3f %6.3f %7.3f\n" % (ditherId, ra, dec, x0, y0, x, y, x-x0, y-y0, mag)
                f.write(line)
    f.close()
       
    print datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")

def writeNewWCS(ditherIds, ccdIds, fitFP, wcsDic, fscale, dims, camera, outputDir="."):
    print "Write New WCS ..."
    iframe = 0;
    img = afwImage.ImageU(0,0)
    for ditherId in ditherIds:
        for ccdId in ccdIds:
            if fitFP:
                ccd = cameraGeomUtils.findCcd(camera, cameraGeom.Id(int(ccdId)))
                offset = ccd.getCenter()
                wcs = wcsDic[ditherIds.index(ditherId)].clone()
                wcs.shiftReferencePixel(-offset[0], -offset[1])
                scale = fscale[ditherIds.index(ditherId)]
            else:
                wcs = wcsDic[iframe]
                scale = fscale[iframe]
            dim = dims[iframe]
            
            ofname = getOutputFileName(outputDir, int(ditherId), int(ccdId))
            md = wcs.getFitsMetadata()
            md.set("FSCALE", scale)
            md.set("NUMAXIS1", dim[0])
            md.set("NUMAXIS2", dim[1])
            img.writeFits(ofname, md)
            iframe += 1
    print datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")
    
def writeNewFitsFiles(ditherIds, ccdIds, wcsDic, fscale, outputDir):
    print "Write New FITS files ..."
    iframe = 0;
    for ditherId in ditherIds:
        for ccdId in ccdIds:
            if fitFP:
                ccd = cameraGeomUtils.findCcd(camera, cameraGeom.Id(int(ccdId)))
                offset = ccd.getCenter()
                wcs = wcsDic[ditherIds.index(ditherId)].clone()
                wcs.shiftReferencePixel(-offset[0], -offset[1])
                scale = fscale[ditherIds.index(ditherId)]
            else:
                wcs = wcsDic[iframe]
                scale = fscale[iframe]
            #fname = "%s/dith%d/out-ssb_ccd%03d-wcs.fits" % (rootdir, int(ditherId), int(ccdId))
            basename = getBasename(int(ditherId), int(ccdId))
            fname = "%s-wcs.fits" % (basename)
            ofname = getOutputFileName(outputDir, int(ditherId), int(ccdId))
            md = dafBase.PropertySet()
            mImg = afwImage.MaskedImageF(fname, 0, md)
            for name in wcs.getFitsMetadata().names():
                md.set(name, wcs.getFitsMetadata().get(name))
            md.set("FSCALE", scale)
            mImg.writeFits(ofname, md)
            del mImg
            iframe += 1
    print datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")
    
def main(ditherIds, ccdIds, outputName=None, fitFP=True, skipMosaic=False, makeWarped=False):
    
    if outputName == None:
        outputName = ''
        for i in range(len(ccdIds)):
            outputName = outputName + "%d-" % (int(ccdIds[i]))

    print datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")
    
    if not skipMosaic:

        print "Mosaicing ..."
        
        mosaic(ditherIds, ccdIds, outputName, fitFP)

        print datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")

    if makeWarped:
        flist = []
        for ditherId in ditherIds:
            for ccdId in ccdIds:
                fname = "%sdith%d_ccd%03d-mImg.fits" % (outputName, int(ditherId), int(ccdId))
                flist.append(fname)

        print "Stacking ..."
        
        stack.stack(flist, outputName, subImgSize=2048, fileIO=False)
        
        print datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")
        
if __name__ == '__main__':

    ditherIds = [0, 1, 2, 3, 4]
    if (len(sys.argv) == 1):
        ccdIds = range(100)
    else:
        ccdIds = sys.argv[1:]
    fitFP = True
    skipMosaic=False
    makeWarped = False

    #main(ditherIds, ccdIds, "test-", fitFP, skipMosaic, makeWarped)
    mosaic(ditherIds, ccdIds, fitFP)
