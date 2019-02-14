from __future__ import with_statement
import sys, os, csv
sys.path.append("/home/albert/lab/scripts/python/imagej/IsoView-GCaMP/")
from lib.synthetic import virtualPointsRAI
from ij3d import Image3DUniverse, Content, ContentCreator
from customnode import CustomMultiMesh, MeshMaker, CustomTriangleMesh
from itertools import islice, imap, izip
from net.imglib2 import FinalInterval, RealPoint
from net.imglib2.view import Views
from net.imglib2.type.numeric.integer import UnsignedByteType
from net.imglib2.img.display.imagej import ImageJVirtualStackUnsignedByte
from ij import ImagePlus, CompositeImage


baseDir = "/home/albert/shares/cardonalab/Albert/2017-05-10_1018/"
# A file whose header has the points as "x::y::z"
csvFilename = "deconvolved/CM00-CM01_deltaFoF.csv"

somaDiameter = 8 # pixels
radius = somaDiameter / 2.0
interval = FinalInterval([406, 465, 325])
minimum = -1.0 # actual min: -5.0
maximum = 2.0 # actual max: 9.4
span = maximum - minimum

def to8bitRange(values):
  return [UnsignedByteType(int((min(max(val, minimum), maximum) / span) * 255)) for val in values]

def withVirtualStack(time_window=None, subsample=None):
  with open(os.path.join(baseDir, csvFilename), 'r') as csvfile:
    reader = csv.reader(csvfile, delimiter=',', quotechar='"')
    header = reader.next()
    peaks = [RealPoint.wrap(imap(float, peak.split('::'))) for peak in islice(header, 1, None)]
    frames = [virtualPointsRAI(peaks, radius, interval, inside=to8bitRange(map(float, islice(row, 1, None)))) for row in reader]
    if time_window:
      first, last = time_window
      frames = frames[first:last+1]
    img4D = Views.stack(frames)
    # Scale by a factor of 'subsample' in every dimension by nearest neighbor, sort of:
    if subsample:
      img4D = Views.subsample(img4D, subsample)
    imp = ImagePlus("deltaF/F", ImageJVirtualStackUnsignedByte.wrap(img4D))
    imp.setDimensions(1, img4D.dimension(2), img4D.dimension(3))
    imp.setDisplayRange(0, 255)
    com = CompositeImage(imp, CompositeImage.GRAYSCALE)
    com.show()
    univ = Image3DUniverse(512, 512)
    univ.show()
    univ.addVoltex(com)


def withIcospheres(time_window=None):
  with open(os.path.join(baseDir, csvFilename), 'r') as csvfile:
    reader = csv.reader(csvfile, delimiter=',', quotechar='"')
    header = reader.next()
    peaks = [RealPoint.wrap(imap(float, peak.split('::'))) for peak in islice(header, 1, None)]
    # Template icosahedron
    ico = MeshMaker.createIcosahedron(2, radius)
    # Share meshes across all timepoints
    icos = [MeshMaker.copyTranslated(ico, peak.dimension(0), peak.dimension(1) , peak.dimension(2)) for peak in peaks]
    #
    univ = Image3DUniverse(512, 512)
    univ.show()
    #
    for row in reader:
      meshes = [CustomTriangleMesh(mesh, Color3f(v, v, v), 0)
                for v, mesh in izip(imap(lambda val: (min(max(val, minimum), maximum) / span), islice(reader, 1, None)), icos)]
      content = ContentCreator.createContent(CustomMultiMesh(meshes), str(row[0]), int(row[0])) # sets the timepoint
      univ.addContentLater(content)



